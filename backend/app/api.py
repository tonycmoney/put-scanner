"""HTTP API for the dashboard. Read only, plus a rate limited manual scan."""

from __future__ import annotations

import time as _time
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_db
from app.models import Pick, ScanRun
from app.scheduler import next_job, parse_times, run_job
from app.service import graded_rows, kv_get, work_lock
from app.strategy.grading import LOSS, OPEN, WIN, bucket_stats, weak_buckets

router = APIRouter(prefix="/api")
_last_manual = {"at": 0.0}


def pick_out(p: Pick) -> dict:
    return {
        "id": p.id,
        "symbol": p.symbol,
        "status": p.status,
        "trade_date": p.trade_date.isoformat(),
        "expiry": p.expiry.isoformat(),
        "close_by": p.close_by.isoformat(),
        "alert_level": p.alert_level,
        "entry_price": p.entry_price,
        "last_price": p.last_price,
        "last_spread_value": p.last_spread_value,
        "score": p.score,
        "short_strike": p.short_strike,
        "long_strike": p.long_strike,
        "credit": p.credit,
        "contracts": p.contracts,
        "est_profit": p.est_profit,
        "max_loss": p.max_loss,
        "pnl": p.pnl,
        "grade_reason": p.grade_reason,
        "buckets": p.buckets,
        "details": p.details,
    }


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/status")
def status_view(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    tz = ZoneInfo(settings.timezone)
    now = datetime.now(tz)
    job = next_job(now, parse_times(settings.scan_times), parse_times(settings.grade_time)[0])
    last = db.scalars(select(ScanRun).order_by(ScanRun.id.desc()).limit(1)).first()
    rules = settings.rules()
    return {
        "configured": settings.webull_configured,
        "environment": settings.webull_env,
        "token_status": kv_get(db, "webull_token_status"),
        "scheduler_enabled": settings.scheduler_enabled,
        "busy": work_lock.locked(),
        "next_job": {"kind": job.kind, "at": job.at.isoformat()},
        "alerts_enabled": bool(settings.alert_webhook_url),
        "last_run": None
        if last is None
        else {
            "id": last.id,
            "status": last.status,
            "trigger": last.trigger,
            "picks": last.picks,
            "candidates": last.candidates,
            "spy_change": last.spy_change,
            "error": last.error,
            "started_at": last.started_at.isoformat(),
            "rejected": last.rejected[:40],
        },
        "rules": {
            "budget": rules.budget,
            "max_loss_per_trade": rules.max_loss_per_trade,
            "profit_target": [rules.profit_target_min, rules.profit_target_max],
            "price_range": [rules.price_min, rules.price_max],
            "min_market_cap": rules.min_market_cap,
            "min_volume": rules.min_volume,
            "min_move": rules.min_move,
            "dte": [rules.dte_min, rules.dte_max],
            "otm": [rules.otm_min, rules.otm_max],
        },
    }


@router.get("/picks")
def list_picks(
    status_filter: str = Query(default="open", alias="status", pattern="^(open|graded|all)$"),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    query = select(Pick).order_by(Pick.id.desc()).limit(limit)
    if status_filter == "open":
        query = query.where(Pick.status == OPEN)
    elif status_filter == "graded":
        query = query.where(Pick.status != OPEN)
    return [pick_out(p) for p in db.scalars(query)]


@router.get("/stats")
def stats(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    rows = graded_rows(db)
    wins = sum(r["outcome"] == WIN for r in rows)
    losses = sum(r["outcome"] == LOSS for r in rows)
    pnl = round(sum(r["pnl"] for r in rows), 2)
    win_pnls = [r["pnl"] for r in rows if r["outcome"] == WIN]
    loss_pnls = [r["pnl"] for r in rows if r["outcome"] == LOSS]
    rules = settings.rules()
    return {
        "graded": len(rows),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(rows), 3) if rows else None,
        "pnl": pnl,
        "avg_win": round(sum(win_pnls) / len(win_pnls), 2) if win_pnls else None,
        "avg_loss": round(sum(loss_pnls) / len(loss_pnls), 2) if loss_pnls else None,
        "buckets": {
            bucket: {
                value: {"trades": s.trades, "wins": s.wins, "pnl": round(s.pnl, 2)}
                for value, s in values.items()
            }
            for bucket, values in bucket_stats(rows).items()
        },
        "adaptation": {
            "active": len(rows) >= rules.min_graded_for_adaptation,
            "graded_needed": rules.min_graded_for_adaptation,
            "filtered": {k: sorted(v) for k, v in weak_buckets(rows, rules).items()},
        },
    }


@router.get("/runs")
def runs(limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)):
    rows = db.scalars(select(ScanRun).order_by(ScanRun.id.desc()).limit(limit))
    return [
        {
            "id": r.id,
            "trigger": r.trigger,
            "status": r.status,
            "picks": r.picks,
            "candidates": r.candidates,
            "rejected": len(r.rejected),
            "spy_change": r.spy_change,
            "error": r.error,
            "started_at": r.started_at.isoformat(),
        }
        for r in rows
    ]


@router.post("/scan", status_code=status.HTTP_202_ACCEPTED)
def manual_scan(settings: Settings = Depends(get_settings)):
    if not settings.webull_configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Webull keys are not configured")
    now = _time.monotonic()
    wait = settings.manual_scan_cooldown_s - (now - _last_manual["at"])
    if _last_manual["at"] and wait > 0:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS, f"Next manual scan available in {int(wait)}s"
        )
    _last_manual["at"] = now
    result = run_job("scan", settings, trigger="manual")
    return {"result": result}
