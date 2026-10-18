"""Stage 1 and 2: which movers are even worth pricing options for."""

from __future__ import annotations

from datetime import date

from app.market import Bar, StockQuote
from app.strategy.rules import Rules

DOWN_SHOCK = "down_shock"
UP_SPIKE = "up_spike"


def classify(q: StockQuote, rules: Rules) -> str | None:
    if q.change_ratio <= -rules.min_move:
        return DOWN_SHOCK
    if q.change_ratio >= rules.min_move:
        return UP_SPIKE
    return None


def basic_screen(q: StockQuote, rules: Rules) -> str | None:
    """Return a rejection reason, or None if the quote passes."""
    if not rules.price_min <= q.price <= rules.price_max:
        return f"price ${q.price:.2f} outside ${rules.price_min:.0f} to ${rules.price_max:.0f}"
    if q.market_cap and q.market_cap < rules.min_market_cap:
        return f"market cap ${q.market_cap / 1e9:.2f}B under ${rules.min_market_cap / 1e9:.0f}B"
    if q.volume < rules.min_volume:
        return f"volume {q.volume / 1000:.0f}K under {rules.min_volume / 1000:.0f}K"
    if classify(q, rules) is None:
        return f"move {q.change_ratio:+.1%} under {rules.min_move:.0%}"
    return None


def straight_new_lows(bars: list[Bar]) -> int:
    """Consecutive most recent sessions that each set a lower low than the one before."""
    count = 0
    for prev, cur in zip(reversed(bars[:-1]), reversed(bars[1:]), strict=False):
        if cur.low < prev.low:
            count += 1
        else:
            break
    return count


def history_screen(q: StockQuote, setup: str, bars: list[Bar], rules: Rules) -> str | None:
    if setup == DOWN_SHOCK:
        streak = straight_new_lows(bars)
        if streak >= rules.straight_new_lows_limit:
            return f"{streak} straight new lows (falling knife)"
        if q.low > 0 and (q.price - q.low) / q.low < rules.at_day_low_pct:
            return "still trading at the day's low"
    return None


def earnings_screen(next_earnings: date | None, latest_expiry: date) -> str | None:
    if next_earnings and next_earnings <= latest_expiry:
        return f"earnings {next_earnings.isoformat()} before expiry"
    return None


def avg_abs_daily_move(bars: list[Bar], days: int = 20) -> float:
    """Typical daily move, excluding the most recent bar (the shock itself)."""
    window = bars[-(days + 1) : -1] if len(bars) > 2 else bars
    moves = [
        abs(b.close / a.close - 1) for a, b in zip(window, window[1:], strict=False) if a.close
    ]
    return sum(moves) / len(moves) if moves else 0.0
