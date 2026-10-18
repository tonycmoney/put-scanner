"""Glue between the scanner, the database and Webull."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alerts import send_alert
from app.config import Settings
from app.market import MarketData, WebullMarketData
from app.models import KeyValue, Pick, ScanRun
from app.scanner import run_scan
from app.strategy.grading import OPEN, grade_spread, weak_buckets
from app.strategy.rules import Rules
from app.webull.client import WebullClient, WebullError

log = logging.getLogger("service")

# One scan or grading pass at a time (scheduler and manual trigger share it).
work_lock = threading.Lock()


class NotConfigured(RuntimeError):
    pass


class TokenPending(RuntimeError):
    pass


def kv_get(db: Session, key: str) -> str | None:
    row = db.get(KeyValue, key)
    return row.value if row else None


def kv_set(db: Session, key: str, value: str) -> None:
    row = db.get(KeyValue, key)
    if row:
        row.value = value
    else:
        db.add(KeyValue(key=key, value=value))
    db.commit()


def connect(settings: Settings, db: Session) -> MarketData:
    """Build an authenticated market data provider, handling the token flow."""
    if not settings.webull_configured:
        raise NotConfigured("Webull App Key and App Secret are not set")
    client = WebullClient(
        settings.webull_app_key,
        settings.webull_app_secret,
        environment=settings.webull_env,
        host=settings.webull_host,
    )
    if client.token_required():
        token = kv_get(db, "webull_token")
        status = None
        if token:
            status = (client.check_token(token) or {}).get("status")
        if not token or status not in ("NORMAL", "PENDING"):
            created = client.create_token() or {}
            token, status = created.get("token"), created.get("status")
            if not token:
                raise WebullError(500, "token create returned no token")
            kv_set(db, "webull_token", token)
        kv_set(db, "webull_token_status", status or "UNKNOWN")
        if status != "NORMAL":
            raise TokenPending("Approve the API access request in the Webull app, then rescan")
        client.access_token = token
    else:
        kv_set(db, "webull_token_status", "NOT_REQUIRED")
    return WebullMarketData(client)


def graded_rows(db: Session) -> list[dict]:
    rows = db.scalars(select(Pick).where(Pick.status != OPEN)).all()
    return [{"outcome": p.status, "pnl": p.pnl, **p.buckets} for p in rows]


def scan(
    db: Session, market: MarketData, rules: Rules, settings: Settings, trigger: str, today: date
) -> ScanRun:
    run = ScanRun(trigger=trigger)
    db.add(run)
    db.commit()
    try:
        open_symbols = set(db.scalars(select(Pick.symbol).where(Pick.status == OPEN)))
        report = run_scan(
            market, rules, today, exclude=open_symbols, weak=weak_buckets(graded_rows(db), rules)
        )
        for p in report.picks:
            details = p.as_dict()
            db.add(
                Pick(
                    scan_run_id=run.id,
                    symbol=p.symbol,
                    trade_date=today,
                    expiry=p.expiry,
                    close_by=p.close_by,
                    alert_level=p.alert_level,
                    entry_price=p.price,
                    score=p.score,
                    short_symbol=p.short_symbol,
                    long_symbol=p.long_symbol,
                    short_strike=p.short_strike,
                    long_strike=p.long_strike,
                    credit=p.credit,
                    contracts=p.contracts,
                    est_profit=p.est_profit,
                    max_loss=p.max_loss,
                    details=details,
                    buckets=p.buckets,
                    last_price=p.price,
                )
            )
        run.status = "ok"
        run.candidates = report.candidates
        run.picks = len(report.picks)
        run.spy_change = report.spy_change
        run.rejected = [{"symbol": s, "reason": r} for s, r in report.rejected]
        send_alert(settings.alert_webhook_url, report.picks)
    except Exception as exc:  # recorded on the run and shown in the UI
        log.exception("scan failed")
        db.rollback()
        run.status = "error"
        run.error = str(exc)[:500]
    run.finished_at = datetime.now(UTC)
    db.add(run)
    db.commit()
    return run


def grade_open_picks(db: Session, market: MarketData, rules: Rules, today: date) -> int:
    picks = list(db.scalars(select(Pick).where(Pick.status == OPEN)))
    if not picks:
        return 0
    quotes = market.snapshots(sorted({p.symbol for p in picks}))
    option_mids = _option_mids(market, picks)
    graded = 0
    for pick in picks:
        quote = quotes.get(pick.symbol)
        if quote is None:
            continue
        spread_value = None
        if pick.short_symbol in option_mids and pick.long_symbol in option_mids:
            spread_value = round(option_mids[pick.short_symbol] - option_mids[pick.long_symbol], 2)
        pick.last_price = quote.price
        pick.last_spread_value = spread_value
        result = grade_spread(
            short_strike=pick.short_strike,
            long_strike=pick.long_strike,
            credit=pick.credit,
            contracts=pick.contracts,
            expiry=pick.expiry,
            close=quote.price,
            today=today,
            spread_value=spread_value,
            rules=rules,
        )
        if result.outcome != OPEN:
            pick.status = result.outcome
            pick.pnl = result.pnl
            pick.grade_reason = result.reason
            pick.graded_at = datetime.now(UTC)
            graded += 1
    db.commit()
    return graded


def _option_mids(market: MarketData, picks: list[Pick]) -> dict[str, float]:
    """Current mid prices for the legs of open picks, when the provider supports it."""
    snapshot = getattr(market, "option_mids", None)
    if snapshot is None:
        return {}
    symbols = sorted({s for p in picks for s in (p.short_symbol, p.long_symbol)})
    try:
        return snapshot(symbols)
    except Exception:  # pricing is a nice to have for grading; closes are enough
        log.warning("option snapshot failed during grading", exc_info=True)
        return {}
