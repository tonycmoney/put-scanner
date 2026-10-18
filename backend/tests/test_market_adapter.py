"""WebullMarketData against a mocked HTTP API with payloads shaped like the real ones."""

from datetime import date

import httpx

from app.market import WebullMarketData
from app.webull.client import WebullClient

GAINERS = {
    "data": [
        {"symbol": "LQDA", "name": "Liquidia", "price": "33.50", "pre_close": "29.91",
         "change_ratio": "0.12", "volume": "4100000", "market_value": "2.8E9",
         "high": "34.1", "low": "30.2", "open": "30.0"},
    ],
    "has_more": False,
}  # fmt: skip
LOSERS = {"data": [{"symbol": "LQDA", "price": "33.50", "change_ratio": "0.12"}]}
BARS = {
    "result": [
        {
            "symbol": "LQDA",
            "result": [
                {"time": "2026-10-13T04:00:00.000+0000", "close": "29.91", "low": "29.5"},
                {"time": "2026-10-12T04:00:00.000+0000", "close": "29.40", "low": "29.0"},
                {"time": "bad", "close": "1"},
            ],
        }
    ]
}
EARNINGS = [
    {"expected_publish_date": "2026-08-05"},
    {"expected_publish_date": "2026-11-06"},
    {"expected_publish_date": "2026-11-20"},
    {"expected_publish_date": ""},
]
CONTRACTS = {
    "data": [
        {"symbol": "LQDA261030P00030000"},
        {"symbol": "LQDA261030P00027500"},
        {"symbol": "LQDA261218P00030000"},  # beyond the window
        {"symbol": "LQDA261030C00030000"},  # call
        {"symbol": "junk"},
    ]
}
OPTION_SNAPSHOTS = [
    {"symbol": "LQDA261030P00030000", "bid": "0.80", "ask": "0.90", "volume": "120",
     "open_interest": "900"},
    {"symbol": "LQDA261030P00027500", "bid": "0.25", "ask": "0.35"},
]  # fmt: skip


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("gainers-losers/list"):
        return httpx.Response(
            200, json=GAINERS if request.url.params["direction"] == "DESC" else LOSERS
        )
    if path.endswith("stocks/snapshots/list"):
        return httpx.Response(200, json=GAINERS["data"])
    if path.endswith("stocks/bars/list"):
        return httpx.Response(200, json=BARS)
    if path.endswith("earnings-calendars/list"):
        return httpx.Response(200, json=EARNINGS)
    if path.endswith("options/contracts/list"):
        return httpx.Response(200, json=CONTRACTS)
    if path.endswith("options/snapshots/list"):
        return httpx.Response(200, json=OPTION_SNAPSHOTS)
    return httpx.Response(404)


def market() -> WebullMarketData:
    client = WebullClient("k", "s", transport=httpx.MockTransport(handler), min_interval_s=0)
    return WebullMarketData(client)


def test_movers_deduplicates_and_parses():
    movers = market().movers()
    assert len(movers) == 1
    m = movers[0]
    assert (m.symbol, m.price, m.change_ratio, m.market_cap) == ("LQDA", 33.5, 0.12, 2.8e9)


def test_snapshots_keyed_by_symbol():
    assert market().snapshots(["LQDA"])["LQDA"].volume == 4_100_000


def test_bars_sorted_and_bad_rows_skipped():
    bars = market().daily_bars(["LQDA"])["LQDA"]
    assert [b.day for b in bars] == [date(2026, 10, 12), date(2026, 10, 13)]


def test_next_earnings_is_first_upcoming():
    assert market().next_earnings("LQDA", date(2026, 10, 14)) == date(2026, 11, 6)
    assert market().next_earnings("LQDA", date(2026, 12, 1)) is None


def test_put_chain_filters_and_joins_quotes():
    chain = market().put_chain("LQDA", date(2026, 10, 24), date(2026, 11, 4), 25, 31)
    assert sorted(o.strike for o in chain) == [27.5, 30.0]
    thirty = next(o for o in chain if o.strike == 30)
    assert round(thirty.mid, 2) == 0.85 and thirty.open_interest == 900 and thirty.put


def test_option_mids():
    mids = market().option_mids(["LQDA261030P00030000", "LQDA261030P00027500"])
    assert mids == {"LQDA261030P00030000": 0.85, "LQDA261030P00027500": 0.3}
