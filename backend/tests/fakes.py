"""In memory market data built from realistic Webull shaped rows."""

from __future__ import annotations

from datetime import date, timedelta

from app.market import Bar, OptionQuote, StockQuote

TODAY = date(2026, 10, 14)  # a Wednesday
EXPIRY = date(2026, 10, 30)


def quote(symbol, price, change, volume=3_000_000, cap=5e9, low=None, name=""):
    prev = price / (1 + change)
    return StockQuote(
        symbol=symbol,
        price=price,
        open=prev,
        high=max(price, prev) * 1.01,
        low=low if low is not None else min(price, prev) * 0.97,
        prev_close=prev,
        change_ratio=change,
        volume=volume,
        market_cap=cap,
        name=name or symbol,
    )


def calm_bars(price, days=25, step=0.01):
    """Gently rising history ending yesterday, with normal ~1% daily moves."""
    bars = []
    p = price * 0.8
    for i in range(days):
        day = TODAY - timedelta(days=days - i)
        bars.append(Bar(day, p, p * 1.01, p * 0.99, p * (1 + step), 1e6))
        p *= 1 + step * (1 if i % 2 else -0.5)
    return bars


def falling_bars(price, days=10):
    bars = []
    p = price * 1.5
    for i in range(days):
        day = TODAY - timedelta(days=days - i)
        bars.append(Bar(day, p, p * 1.01, p * 0.96, p * 0.97, 1e6))
        p *= 0.95
    return bars


def put(symbol, strike, bid, ask, expiry=EXPIRY):
    occ = f"{symbol}{expiry:%y%m%d}P{int(strike * 1000):08d}"
    return OptionQuote(occ, symbol, expiry, strike, True, bid, ask, (bid + ask) / 2, 500, 2000)


def chain(symbol, price, expiry=EXPIRY):
    """Strikes every $1 from 25% below to at the money, premium decaying with distance."""
    out = []
    strike = round(price * 0.75)
    while strike <= price:
        otm = 1 - strike / price
        mid = max(0.05, price * 0.06 * (1 - otm / 0.25) ** 2)
        out.append(put(symbol, float(strike), round(mid * 0.92, 2), round(mid * 1.08, 2), expiry))
        strike += 1
    return out


class FakeMarket:
    def __init__(self, movers, bars=None, earnings=None, chains=None, spy_change=0.002):
        self._movers = movers
        self._bars = bars or {}
        self._earnings = earnings or {}
        self._chains = chains or {}
        self.spy = quote("SPY", 580, spy_change)
        self.calls = {"put_chain": 0}

    def movers(self):
        return list(self._movers)

    def snapshots(self, symbols):
        known = {q.symbol: q for q in [*self._movers, self.spy]}
        return {s: known[s] for s in symbols if s in known}

    def daily_bars(self, symbols, count=30):
        return {s: self._bars.get(s, calm_bars(50)) for s in symbols}

    def next_earnings(self, symbol, today):
        return self._earnings.get(symbol)

    def put_chain(self, symbol, expiry_from, expiry_to, strike_min, strike_max):
        self.calls["put_chain"] += 1
        rows = self._chains.get(symbol, [])
        return [
            o
            for o in rows
            if expiry_from <= o.expiry <= expiry_to and strike_min <= o.strike <= strike_max
        ]
