"""Grade open picks and learn from the results.

A spread pick is a LOSS if the stock closes below the short strike (the
alert level) at any close before expiry, a WIN if the spread can be bought
back for half the credit or less, and a WIN at expiry if the stock closes
at or above the short strike.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from app.strategy.rules import Rules

OPEN, WIN, LOSS = "open", "win", "loss"


@dataclass
class Grade:
    outcome: str
    pnl: float = 0.0
    reason: str = ""


def grade_spread(
    *,
    short_strike: float,
    long_strike: float,
    credit: float,
    contracts: int,
    expiry: date,
    close: float,
    today: date,
    spread_value: float | None,
    rules: Rules,
) -> Grade:
    width = short_strike - long_strike
    if close < short_strike:
        # Closed under the alert: assume we exit at the current spread value,
        # or intrinsic value when no quote is available.
        value = spread_value if spread_value is not None else min(width, short_strike - close)
        pnl = round((credit - value) * 100 * contracts, 2)
        return Grade(LOSS, pnl, f"closed {close:.2f} under the {short_strike:.2f} alert")
    if spread_value is not None and spread_value <= credit * rules.take_profit_fraction:
        pnl = round((credit - spread_value) * 100 * contracts, 2)
        return Grade(WIN, pnl, f"spread worth {spread_value:.2f}, hit the 50% profit target")
    if today >= expiry:
        return Grade(WIN, round(credit * 100 * contracts, 2), "expired above the short strike")
    return Grade(OPEN)


BUCKETS = ("setup", "score_band", "strike_distance", "spy_direction")


def strike_distance_bucket(otm: float) -> str:
    return "10%+" if otm >= 0.10 else "under 10%"


def spy_bucket(change: float) -> str:
    return "SPY up" if change >= 0 else "SPY down"


@dataclass
class BucketStat:
    trades: int = 0
    wins: int = 0
    pnl: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0


def bucket_stats(graded: list[dict]) -> dict[str, dict[str, BucketStat]]:
    """graded rows need: outcome, pnl and one key per bucket dimension."""
    stats: dict[str, dict[str, BucketStat]] = {b: defaultdict(BucketStat) for b in BUCKETS}
    for row in graded:
        for bucket in BUCKETS:
            stat = stats[bucket][row[bucket]]
            stat.trades += 1
            stat.wins += row["outcome"] == WIN
            stat.pnl += row["pnl"]
    return {b: dict(v) for b, v in stats.items()}


def weak_buckets(graded: list[dict], rules: Rules) -> dict[str, set[str]]:
    """Buckets that have lost often enough to start filtering them out.

    Only kicks in once enough picks are graded, so a single bad day doesn't
    rewrite the strategy.
    """
    if len(graded) < rules.min_graded_for_adaptation:
        return {}
    weak: dict[str, set[str]] = {}
    for bucket, values in bucket_stats(graded).items():
        for value, stat in values.items():
            if (
                stat.trades >= rules.weak_bucket_min_trades
                and stat.win_rate < rules.weak_bucket_win_rate
            ):
                weak.setdefault(bucket, set()).add(value)
    return weak
