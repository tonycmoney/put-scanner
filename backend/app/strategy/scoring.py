"""Stage 4: a 0 to 100 score so the best setups surface first.

Each component is capped and explained, so a reviewer can see why a pick
ranked where it did.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.market import StockQuote
from app.strategy.screen import DOWN_SHOCK
from app.strategy.trades import Spread


@dataclass
class Score:
    total: int
    parts: dict[str, int] = field(default_factory=dict)


def score_setup(
    q: StockQuote, setup: str, spread: Spread, typical_move: float, spy_change: float
) -> Score:
    parts: dict[str, int] = {}

    # 1. How unusual the move is versus the stock's normal daily move (25).
    sigma = abs(q.change_ratio) / typical_move if typical_move else 2.0
    parts["move_vs_normal"] = round(min(25, sigma * 6))

    # 2. Cushion: how far the short strike sits below the price (25).
    otm = 1 - spread.short.strike / q.price
    parts["strike_cushion"] = round(min(25, max(0, (otm - 0.05) / 0.10 * 25)))

    # 3. Premium quality: credit as a share of the width (20).
    ratio = spread.credit / spread.width if spread.width else 0
    parts["credit_quality"] = round(min(20, ratio / 0.30 * 20))

    # 4. Liquidity: share volume and option bid/ask tightness (15).
    vol_pts = min(8, q.volume / 2_000_000 * 8)
    short = spread.short
    spread_pct = (short.ask - short.bid) / short.mid if short.mid else 1
    tight_pts = max(0, 7 - spread_pct * 14)
    parts["liquidity"] = round(vol_pts + tight_pts)

    # 5. Market backdrop: selling puts into a falling market is riskier (15).
    if spy_change >= 0:
        regime = 15
    elif spy_change > -0.01:
        regime = 9
    else:
        regime = 4
    if setup == DOWN_SHOCK and spy_change < -0.01:
        regime = 2
    parts["market_backdrop"] = regime

    return Score(total=max(0, min(100, sum(parts.values()))), parts=parts)


def score_band(score: int) -> str:
    if score >= 80:
        return "80+"
    if score >= 70:
        return "70-79"
    if score >= 60:
        return "60-69"
    return "under 60"
