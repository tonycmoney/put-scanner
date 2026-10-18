"""One scan: movers -> screens -> option pricing -> sizing -> score -> top picks.

Pure orchestration over the MarketData protocol, so a whole scan can be
tested with fixtures.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta

from app.market import MarketData, StockQuote
from app.strategy import screen
from app.strategy.grading import spy_bucket, strike_distance_bucket
from app.strategy.rules import Rules
from app.strategy.scoring import score_band, score_setup
from app.strategy.trades import build_spreads, cash_secured_put, choose_expiry, close_by


@dataclass
class Proposal:
    symbol: str
    name: str
    setup: str
    price: float
    change_ratio: float
    score: int
    score_parts: dict[str, int]
    expiry: date
    close_by: date
    alert_level: float
    # Put credit spread
    short_symbol: str
    long_symbol: str
    short_strike: float
    long_strike: float
    credit: float
    natural_credit: float
    contracts: int
    est_profit: float
    max_loss: float
    spread_capital: float
    spread_breakeven: float
    # Cash secured put on the same strike
    csp_contracts: int
    csp_premium: float
    csp_collateral: float
    csp_est_profit: float
    csp_breakeven: float
    # Buckets used for learning
    strike_otm: float
    spy_change: float
    buckets: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        data = asdict(self)
        data["expiry"] = self.expiry.isoformat()
        data["close_by"] = self.close_by.isoformat()
        return data


@dataclass
class ScanReport:
    picks: list[Proposal]
    rejected: list[tuple[str, str]]
    candidates: int
    spy_change: float


def run_scan(
    market: MarketData,
    rules: Rules,
    today: date,
    *,
    exclude: set[str] | None = None,
    weak: dict[str, set[str]] | None = None,
) -> ScanReport:
    exclude = exclude or set()
    weak = weak or {}
    rejected: list[tuple[str, str]] = []

    spy = market.snapshots(["SPY"]).get("SPY")
    spy_change = spy.change_ratio if spy else 0.0

    # Stage 1: movers that pass price, cap, volume and size of move.
    movers: list[tuple[StockQuote, str]] = []
    for q in market.movers():
        if q.symbol in exclude:
            continue
        reason = screen.basic_screen(q, rules)
        if reason:
            continue  # the long tail of the screener; not worth logging
        movers.append((q, screen.classify(q, rules)))
    movers.sort(key=lambda m: -abs(m[0].change_ratio))
    movers = movers[:25]  # bound API calls per scan

    # Stage 2: price history and earnings.
    bars = market.daily_bars([q.symbol for q, _ in movers], count=30) if movers else {}
    latest_expiry = today + timedelta(days=rules.dte_max)
    survivors = []
    for q, setup in movers:
        history = bars.get(q.symbol, [])
        reason = screen.history_screen(q, setup, history, rules)
        reason = reason or screen.earnings_screen(
            market.next_earnings(q.symbol, today), latest_expiry
        )
        if reason:
            rejected.append((q.symbol, reason))
            continue
        survivors.append((q, setup, screen.avg_abs_daily_move(history)))

    # Stage 3 and 4: price the options, size, score.
    picks: list[Proposal] = []
    for q, setup, typical in survivors:
        strike_min = q.price * (1 - rules.otm_max) - max(rules.spread_widths)
        strike_max = q.price * (1 - rules.otm_min)
        chain = market.put_chain(
            q.symbol,
            today + timedelta(days=rules.dte_min),
            latest_expiry,
            strike_min,
            strike_max,
        )
        expiry = choose_expiry(chain, today, rules)
        if expiry is None:
            rejected.append((q.symbol, "no listed puts in the expiry window"))
            continue
        spreads = build_spreads(q.price, chain, expiry, rules)
        spreads = [s for s in spreads if s.est_profit >= rules.min_est_profit]
        if not spreads:
            rejected.append(
                (q.symbol, f"no spread with est profit over ${rules.min_est_profit:.0f}")
            )
            continue

        scored = [(score_setup(q, setup, s, typical, spy_change), s) for s in spreads]
        best_score, best = max(scored, key=lambda x: x[0].total)
        otm = 1 - best.short.strike / q.price
        buckets = {
            "setup": setup,
            "score_band": score_band(best_score.total),
            "strike_distance": strike_distance_bucket(otm),
            "spy_direction": spy_bucket(spy_change),
        }
        weak_hits = [f"{k}={v}" for k, v in buckets.items() if v in weak.get(k, set())]
        if weak_hits:
            rejected.append((q.symbol, f"historically weak: {', '.join(weak_hits)}"))
            continue

        csp = cash_secured_put(best.short, rules)
        warnings = []
        if best.est_profit < rules.profit_target_min:
            warnings.append(f"est profit under the ${rules.profit_target_min:.0f} target")
        if best.natural_credit < best.credit * 0.7:
            warnings.append("wide bid/ask: use a limit order near the mid")
        if csp is None:
            warnings.append("strike too high for a cash secured put within the budget")

        picks.append(
            Proposal(
                symbol=q.symbol,
                name=q.name,
                setup=setup,
                price=q.price,
                change_ratio=q.change_ratio,
                score=best_score.total,
                score_parts=best_score.parts,
                expiry=expiry,
                close_by=close_by(expiry, rules),
                alert_level=best.short.strike,
                short_symbol=best.short.symbol,
                long_symbol=best.long.symbol,
                short_strike=best.short.strike,
                long_strike=best.long.strike,
                credit=best.credit,
                natural_credit=best.natural_credit,
                contracts=best.contracts,
                est_profit=best.est_profit,
                max_loss=best.max_loss,
                spread_capital=best.capital_required,
                spread_breakeven=best.breakeven,
                csp_contracts=csp.contracts if csp else 0,
                csp_premium=csp.premium if csp else 0.0,
                csp_collateral=csp.collateral if csp else 0.0,
                csp_est_profit=csp.est_profit if csp else 0.0,
                csp_breakeven=csp.breakeven if csp else 0.0,
                strike_otm=round(otm, 4),
                spy_change=spy_change,
                buckets=buckets,
                warnings=warnings,
            )
        )

    picks.sort(key=lambda p: -p.score)
    return ScanReport(
        picks=picks[: rules.max_picks],
        rejected=rejected,
        candidates=len(movers),
        spy_change=spy_change,
    )
