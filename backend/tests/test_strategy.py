from datetime import date, timedelta

import pytest

from app.market import Bar, StockQuote, num, parse_occ
from app.scanner import run_scan
from app.strategy import screen
from app.strategy.grading import LOSS, OPEN, WIN, bucket_stats, grade_spread, weak_buckets
from app.strategy.rules import Rules
from app.strategy.trades import (
    build_spreads,
    cash_secured_put,
    choose_expiry,
    close_by,
    round_nickel,
    size_spread,
)
from tests.fakes import EXPIRY, TODAY, FakeMarket, calm_bars, chain, falling_bars, put, quote

RULES = Rules()

# Parsing


def test_parse_occ():
    assert parse_occ("AAPL260522P00300000") == ("AAPL", date(2026, 5, 22), True, 300.0)
    assert parse_occ("Z261030P00027500") == ("Z", date(2026, 10, 30), True, 27.5)
    assert parse_occ("AAPL260522C00300000")[2] is False
    assert parse_occ("not an option") is None


def test_stock_quote_from_webull_row():
    row = {  # shape returned by /market-data/stocks/snapshots/list
        "symbol": "BSP", "price": "47.0700", "open": "54.8600", "high": "57.5000",
        "low": "46.2005", "volume": "5778797", "pre_close": "55.770000",
        "change_ratio": "-0.155998", "market_value": "29899772921.7000",
    }  # fmt: skip
    q = StockQuote.from_row(row)
    assert q.price == 47.07 and q.change_ratio == pytest.approx(-0.156, abs=1e-3)
    assert q.market_cap == pytest.approx(2.99e10, rel=1e-3)


def test_bar_from_webull_row():
    bar = Bar.from_row({"time": "2026-10-16T04:00:00.000+0000", "close": "30.82", "low": "30.4"})
    assert bar.day == date(2026, 10, 16) and bar.close == 30.82


def test_num_falls_back():
    assert num({"a": "", "b": "2"}, "a", "b") == 2.0
    assert num({"a": "x"}, "a", default=7) == 7


# Screens


@pytest.mark.parametrize(
    ("q", "fragment"),
    [
        (quote("A", 12, -0.10), "price"),
        (quote("B", 70, -0.10), "price"),
        (quote("C", 30, -0.10, cap=5e8), "market cap"),
        (quote("D", 30, -0.10, volume=200_000), "volume"),
        (quote("E", 30, -0.02), "move"),
    ],
)
def test_basic_screen_rejections(q, fragment):
    assert fragment in screen.basic_screen(q, RULES)


def test_basic_screen_pass_and_classify():
    down, up = quote("F", 30, -0.12), quote("G", 30, 0.09)
    assert screen.basic_screen(down, RULES) is None
    assert screen.classify(down, RULES) == screen.DOWN_SHOCK
    assert screen.classify(up, RULES) == screen.UP_SPIKE


def test_straight_new_lows():
    assert screen.straight_new_lows(falling_bars(40, days=6)) == 5
    assert screen.straight_new_lows(calm_bars(40)) < 3
    assert screen.straight_new_lows([]) == 0


def test_down_shock_at_day_low_rejected():
    q = quote("H", 30, -0.10, low=29.9)
    assert "day's low" in screen.history_screen(q, screen.DOWN_SHOCK, calm_bars(30), RULES)


def test_up_spike_ignores_new_low_rules():
    q = quote("I", 30, 0.10)
    assert screen.history_screen(q, screen.UP_SPIKE, falling_bars(30), RULES) is None


def test_earnings_before_expiry():
    assert "earnings" in screen.earnings_screen(date(2026, 10, 21), EXPIRY)
    assert screen.earnings_screen(date(2026, 11, 4), EXPIRY) is None
    assert screen.earnings_screen(None, EXPIRY) is None


# Trade construction and sizing


def test_round_nickel():
    assert round_nickel(0.57) == 0.55 and round_nickel(0.58) == 0.6


def test_size_spread_caps_risk_and_profit():
    # $2.50 wide, $0.55 credit -> $195 risk per contract -> 1 contract under the $250 cap
    assert size_spread(2.5, 0.55, RULES) == 1
    # $5 wide for $0.20 risks $480 each: over the cap, so zero
    assert size_spread(5, 0.2, RULES) == 0
    # Tiny risk per contract is capped by the $500 profit ceiling
    generous = Rules(budget=100_000)
    n = size_spread(1, 0.9, generous)
    assert 0.9 * 100 * n <= generous.profit_target_max


def test_build_spreads_respect_otm_band_and_risk():
    puts = chain("Z", 31.0)
    spreads = build_spreads(31.0, puts, EXPIRY, RULES)
    assert spreads
    for s in spreads:
        otm = 1 - s.short.strike / 31.0
        assert RULES.otm_min <= otm <= RULES.otm_max
        assert s.max_loss <= RULES.max_loss_per_trade
        assert s.width in RULES.spread_widths
        assert s.credit > 0 and s.breakeven < s.short.strike


def test_choose_expiry_window():
    near = put("Z", 27, 0.5, 0.6, expiry=TODAY + timedelta(days=5))
    good = put("Z", 27, 0.5, 0.6, expiry=TODAY + timedelta(days=16))
    later = put("Z", 27, 0.5, 0.6, expiry=TODAY + timedelta(days=19))
    assert choose_expiry([near, later, good], TODAY, RULES) == good.expiry
    assert choose_expiry([near], TODAY, RULES) is None


def test_cash_secured_put_sizing():
    csp = cash_secured_put(put("Z", 27, 0.40, 0.50), RULES)
    assert csp.contracts == 1  # $2,700 collateral fits a $5,000 budget once
    assert csp.collateral == 2700 and csp.est_profit == 45
    assert cash_secured_put(put("Q", 55, 1, 1.2), RULES) is None  # $5,500 > budget


def test_close_by_skips_weekend():
    assert close_by(date(2026, 10, 30), RULES) == date(2026, 10, 28)
    assert close_by(date(2026, 11, 2), RULES) == date(2026, 10, 30)  # Sat -> Fri


# Full scan


def test_scan_end_to_end_picks_and_rejections():
    good = quote("LQDA", 33.5, 0.12, name="Liquidia")
    knife = quote("KNIF", 40, -0.10)
    earnings = quote("EARN", 45, -0.08)
    nochain = quote("NOOP", 30, 0.07)
    junk = quote("PENNY", 3, -0.4)
    market = FakeMarket(
        movers=[good, knife, earnings, nochain, junk],
        bars={"KNIF": falling_bars(40)},
        earnings={"EARN": date(2026, 10, 21)},
        chains={"LQDA": chain("LQDA", 33.5), "EARN": chain("EARN", 45)},
    )
    report = run_scan(market, RULES, TODAY)

    assert [p.symbol for p in report.picks] == ["LQDA"]
    pick = report.picks[0]
    assert pick.setup == "up_spike"
    assert pick.max_loss <= RULES.max_loss_per_trade
    assert pick.est_profit >= RULES.min_est_profit
    assert pick.alert_level == pick.short_strike
    assert pick.csp_contracts >= 1 and pick.csp_collateral <= RULES.budget
    assert 0 <= pick.score <= 100 and sum(pick.score_parts.values()) == pick.score
    assert pick.expiry == EXPIRY and pick.close_by == date(2026, 10, 28)

    reasons = dict(report.rejected)
    assert "straight new lows" in reasons["KNIF"]
    assert "earnings" in reasons["EARN"]
    assert "no listed puts" in reasons["NOOP"]
    assert "PENNY" not in reasons  # dropped silently at the first screen
    assert market.calls["put_chain"] == 2  # never priced options for rejected names


def test_scan_respects_exclusions_max_picks_and_weak_buckets():
    movers = [quote(f"S{i}", 30 + i, 0.06 + i / 100) for i in range(8)]
    market = FakeMarket(movers=movers, chains={q.symbol: chain(q.symbol, q.price) for q in movers})
    report = run_scan(market, RULES, TODAY, exclude={"S0"})
    assert len(report.picks) == RULES.max_picks
    assert "S0" not in {p.symbol for p in report.picks}
    assert report.picks == sorted(report.picks, key=lambda p: -p.score)

    blocked = run_scan(market, RULES, TODAY, weak={"setup": {"up_spike"}})
    assert blocked.picks == []
    assert all("historically weak" in r for _, r in blocked.rejected)


def test_falling_market_lowers_scores():
    q = quote("LQDA", 33.5, -0.12, low=31)
    calm = run_scan(FakeMarket([q], chains={"LQDA": chain("LQDA", 33.5)}), RULES, TODAY)
    rough = run_scan(
        FakeMarket([q], chains={"LQDA": chain("LQDA", 33.5)}, spy_change=-0.015), RULES, TODAY
    )
    assert rough.picks[0].score < calm.picks[0].score
    assert rough.picks[0].buckets["spy_direction"] == "SPY down"


# Grading and learning


def grade(**kw):
    base = dict(
        short_strike=30, long_strike=27.5, credit=0.55, contracts=1, expiry=EXPIRY,
        close=33, today=TODAY, spread_value=None, rules=RULES,
    )  # fmt: skip
    base.update(kw)
    return grade_spread(**base)


def test_grade_loss_when_close_under_alert():
    g = grade(close=29.0)
    assert g.outcome == LOSS and g.pnl == pytest.approx((0.55 - 1.0) * 100)
    assert grade(close=29.0, spread_value=0.79).pnl == pytest.approx(-24)


def test_grade_take_profit_and_expiry_win():
    assert grade(spread_value=0.25).outcome == WIN
    assert grade(spread_value=0.30).outcome == OPEN
    expired = grade(today=EXPIRY)
    assert expired.outcome == WIN and expired.pnl == 55


def row(outcome, setup="up_spike", band="70-79"):
    return {
        "outcome": outcome, "pnl": 50 if outcome == WIN else -100, "setup": setup,
        "score_band": band, "strike_distance": "10%+", "spy_direction": "SPY up",
    }  # fmt: skip


def test_bucket_stats():
    stats = bucket_stats([row(WIN), row(LOSS), row(WIN, setup="down_shock")])
    assert stats["setup"]["up_spike"].trades == 2
    assert stats["setup"]["up_spike"].win_rate == 0.5
    assert stats["setup"]["down_shock"].pnl == 50


def test_weak_buckets_need_enough_history():
    losing = [row(LOSS, setup="down_shock") for _ in range(5)]
    assert weak_buckets(losing, RULES) == {}  # under 8 graded
    history = losing + [row(WIN) for _ in range(4)]
    assert weak_buckets(history, RULES) == {"setup": {"down_shock"}}
