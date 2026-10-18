"""Stage 3: turn a put chain into sized trades.

Every pick is shown two ways, side by side:
  * a put credit spread (defined risk, sized so max loss <= 5% of budget)
  * a cash secured put on the same strike (sized to the cash budget)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta

from app.market import OptionQuote
from app.strategy.rules import Rules


def round_nickel(x: float) -> float:
    return round(round(x * 20) / 20, 2)


@dataclass(frozen=True)
class Spread:
    short: OptionQuote
    long: OptionQuote
    credit: float  # per share, from mids
    natural_credit: float  # per share, sell at bid / buy at ask (worst fill)
    contracts: int

    @property
    def width(self) -> float:
        return round(self.short.strike - self.long.strike, 2)

    @property
    def max_loss(self) -> float:
        return round((self.width - self.credit) * 100 * self.contracts, 2)

    @property
    def est_profit(self) -> float:
        return round(self.credit * 100 * self.contracts, 2)

    @property
    def capital_required(self) -> float:
        return round(self.width * 100 * self.contracts, 2)  # broker margin for the spread

    @property
    def breakeven(self) -> float:
        return round(self.short.strike - self.credit, 2)


@dataclass(frozen=True)
class CashSecuredPut:
    option: OptionQuote
    premium: float  # per share
    contracts: int

    @property
    def collateral(self) -> float:
        return round(self.option.strike * 100 * self.contracts, 2)

    @property
    def est_profit(self) -> float:
        return round(self.premium * 100 * self.contracts, 2)

    @property
    def breakeven(self) -> float:
        return round(self.option.strike - self.premium, 2)


def choose_expiry(chain: list[OptionQuote], today: date, rules: Rules) -> date | None:
    """Nearest listed expiry inside the DTE window."""
    lo = today + timedelta(days=rules.dte_min)
    hi = today + timedelta(days=rules.dte_max)
    expiries = sorted({o.expiry for o in chain if lo <= o.expiry <= hi})
    return expiries[0] if expiries else None


def size_spread(width: float, credit: float, rules: Rules) -> int:
    risk_per = (width - credit) * 100
    if credit <= 0 or risk_per <= 0:
        return 0
    n = math.floor(rules.max_loss_per_trade / risk_per)
    # Don't size past the top of the profit target.
    if n > 0 and credit * 100 * n > rules.profit_target_max:
        n = max(1, math.floor(rules.profit_target_max / (credit * 100)))
    return n


def build_spreads(
    price: float, chain: list[OptionQuote], expiry: date, rules: Rules
) -> list[Spread]:
    puts = sorted((o for o in chain if o.put and o.expiry == expiry), key=lambda o: o.strike)
    by_strike = {o.strike: o for o in puts}
    spreads = []
    for short in puts:
        otm = 1 - short.strike / price
        if not rules.otm_min <= otm <= rules.otm_max or short.bid <= 0:
            continue
        for width in rules.spread_widths:
            long = by_strike.get(round(short.strike - width, 2))
            if long is None:
                continue
            credit = round_nickel(short.mid - long.mid)
            natural = round(short.bid - long.ask, 2)
            contracts = size_spread(width, credit, rules)
            if credit <= 0 or contracts < 1:
                continue
            spreads.append(Spread(short, long, credit, natural, contracts))
            break  # narrowest available width for this short strike
    return spreads


def cash_secured_put(option: OptionQuote, rules: Rules) -> CashSecuredPut | None:
    contracts = math.floor(rules.budget / (option.strike * 100))
    premium = round_nickel(option.mid)
    if contracts < 1 or premium <= 0:
        return None
    return CashSecuredPut(option, premium, contracts)


def close_by(expiry: date, rules: Rules) -> date:
    day = expiry - timedelta(days=rules.close_by_days_before_expiry)
    while day.weekday() >= 5:  # roll back off the weekend
        day -= timedelta(days=1)
    return day
