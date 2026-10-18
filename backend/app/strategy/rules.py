"""The put selling rules, in one place.

Defaults reproduce the hand run scanner this service replaces: a $5,000
cash secured budget, at most 5% of the budget at risk per trade, a $100 to
$500 profit target, and the screening rules that were applied each run.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Rules:
    budget: float = 5000.0
    max_loss_pct: float = 0.05  # of budget, per trade
    profit_target_min: float = 100.0
    profit_target_max: float = 500.0
    min_est_profit: float = 50.0  # below this a setup isn't worth the commissions

    price_min: float = 15.0
    price_max: float = 60.0
    min_market_cap: float = 1_000_000_000
    min_volume: float = 500_000
    min_move: float = 0.05  # day move that counts as a shock or spike

    dte_min: int = 10
    dte_max: int = 21
    otm_min: float = 0.07  # short strike at least 7% below price
    otm_max: float = 0.16
    spread_widths: tuple[float, ...] = (2.5, 3.0, 5.0)
    close_by_days_before_expiry: int = 2
    take_profit_fraction: float = 0.5  # close when the spread has lost 50% of its value

    max_picks: int = 5
    straight_new_lows_limit: int = 3
    at_day_low_pct: float = 0.015  # down shock still within 1.5% of its low
    min_graded_for_adaptation: int = 8
    weak_bucket_min_trades: int = 4
    weak_bucket_win_rate: float = 0.35

    @property
    def max_loss_per_trade(self) -> float:
        return self.budget * self.max_loss_pct
