"""Market data types, parsing, and the provider the scanner depends on.

The scanner talks to the `MarketData` protocol, not to Webull directly, so
strategy code is tested against fixtures and the data source is swappable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from app.webull.client import WebullClient

OCC = re.compile(r"^(?P<root>[A-Z.]{1,6})(?P<ymd>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")


def num(row: dict, *keys: str, default: float = 0.0) -> float:
    """First present numeric field; Webull returns numbers as strings."""
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return default


@dataclass(frozen=True)
class StockQuote:
    symbol: str
    price: float
    open: float
    high: float
    low: float
    prev_close: float
    change_ratio: float  # -0.12 means down 12%
    volume: float
    market_cap: float
    name: str = ""

    @classmethod
    def from_row(cls, row: dict) -> StockQuote:
        price = num(row, "price", "close")
        prev = num(row, "pre_close")
        ratio = num(row, "change_ratio", default=(price / prev - 1) if prev else 0.0)
        return cls(
            symbol=str(row.get("symbol", "")).upper(),
            price=price,
            open=num(row, "open"),
            high=num(row, "high"),
            low=num(row, "low"),
            prev_close=prev,
            change_ratio=ratio,
            volume=num(row, "volume"),
            market_cap=num(row, "market_value", "market_cap"),
            name=str(row.get("name", "")),
        )


@dataclass(frozen=True)
class Bar:
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float

    @classmethod
    def from_row(cls, row: dict) -> Bar:
        raw = str(row.get("time") or row.get("date") or "")[:10]
        return cls(
            day=date.fromisoformat(raw),
            open=num(row, "open"),
            high=num(row, "high"),
            low=num(row, "low"),
            close=num(row, "close"),
            volume=num(row, "volume"),
        )


@dataclass(frozen=True)
class OptionQuote:
    symbol: str
    underlying: str
    expiry: date
    strike: float
    put: bool
    bid: float
    ask: float
    last: float = 0.0
    volume: float = 0.0
    open_interest: float = 0.0

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2
        return self.last or self.bid or self.ask


def parse_occ(symbol: str) -> tuple[str, date, bool, float] | None:
    """'AAPL260522P00300000' -> ('AAPL', 2026-05-22, True, 300.0)."""
    match = OCC.match(symbol.replace(" ", "").upper())
    if not match:
        return None
    ymd = match["ymd"]
    expiry = date(2000 + int(ymd[:2]), int(ymd[2:4]), int(ymd[4:]))
    return match["root"], expiry, match["cp"] == "P", int(match["strike"]) / 1000


class MarketData(Protocol):
    def movers(self) -> list[StockQuote]: ...
    def snapshots(self, symbols: list[str]) -> dict[str, StockQuote]: ...
    def daily_bars(self, symbols: list[str], count: int = 30) -> dict[str, list[Bar]]: ...
    def next_earnings(self, symbol: str, today: date) -> date | None: ...
    def put_chain(
        self, symbol: str, expiry_from: date, expiry_to: date, strike_min: float, strike_max: float
    ) -> list[OptionQuote]: ...


class WebullMarketData:
    """Adapts the raw Webull client to the MarketData protocol."""

    def __init__(self, client: WebullClient) -> None:
        self.client = client

    def movers(self) -> list[StockQuote]:
        rows = self.client.gainers_losers("DESC") + self.client.gainers_losers("ASC")
        seen: dict[str, StockQuote] = {}
        for row in rows:
            quote = StockQuote.from_row(row)
            if quote.symbol:
                seen.setdefault(quote.symbol, quote)  # first (richer) row wins
        return list(seen.values())

    def snapshots(self, symbols: list[str]) -> dict[str, StockQuote]:
        return {
            q.symbol: q
            for q in (StockQuote.from_row(r) for r in self.client.stock_snapshots(symbols))
        }

    def daily_bars(self, symbols: list[str], count: int = 30) -> dict[str, list[Bar]]:
        raw = self.client.daily_bars(symbols, count)
        out = {}
        for symbol, rows in raw.items():
            bars = []
            for row in rows:
                try:
                    bars.append(Bar.from_row(row))
                except ValueError:
                    continue
            out[symbol] = sorted(bars, key=lambda b: b.day)
        return out

    def next_earnings(self, symbol: str, today: date) -> date | None:
        upcoming = []
        for row in self.client.earnings_calendar(symbol):
            raw = str(row.get("expected_publish_date") or row.get("publish_date") or "")[:10]
            try:
                day = date.fromisoformat(raw)
            except ValueError:
                continue
            if day >= today:
                upcoming.append(day)
        return min(upcoming) if upcoming else None

    def option_mids(self, option_symbols: list[str]) -> dict[str, float]:
        """Current mid price per option symbol (used when grading open spreads)."""
        out = {}
        for row in self.client.option_snapshots(option_symbols):
            bid, ask = num(row, "bid", "bid_price"), num(row, "ask", "ask_price")
            mid = (bid + ask) / 2 if bid > 0 and ask > 0 else num(row, "price", "last")
            if row.get("symbol"):
                out[str(row["symbol"])] = round(mid, 2)
        return out

    def put_chain(
        self, symbol: str, expiry_from: date, expiry_to: date, strike_min: float, strike_max: float
    ) -> list[OptionQuote]:
        contracts = self.client.put_contracts(
            symbol, expiry_from.isoformat(), strike_min, strike_max
        )
        wanted: dict[str, tuple[str, date, bool, float]] = {}
        for row in contracts:
            occ = str(row.get("symbol") or row.get("option_symbol") or "")
            parsed = parse_occ(occ)
            if parsed and parsed[2] and expiry_from <= parsed[1] <= expiry_to:
                wanted[occ] = parsed
        if not wanted:
            return []
        quotes = []
        for row in self.client.option_snapshots(list(wanted)):
            occ = str(row.get("symbol") or row.get("option_symbol") or "")
            if occ not in wanted:
                continue
            root, expiry, is_put, strike = wanted[occ]
            quotes.append(
                OptionQuote(
                    symbol=occ,
                    underlying=symbol,
                    expiry=expiry,
                    strike=strike,
                    put=is_put,
                    bid=num(row, "bid", "bid_price"),
                    ask=num(row, "ask", "ask_price"),
                    last=num(row, "price", "last", "close"),
                    volume=num(row, "volume"),
                    open_interest=num(row, "open_interest", "open_int"),
                )
            )
        return quotes


def to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    return value
