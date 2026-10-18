from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from app import api, service
from app.alerts import format_pick, send_alert
from app.config import Settings
from app.models import Pick, ScanRun
from app.scanner import run_scan
from app.scheduler import next_job, parse_times
from app.strategy.rules import Rules
from tests.fakes import EXPIRY, TODAY, FakeMarket, chain, quote

NY = ZoneInfo("America/New_York")
RULES = Rules()


def market_with(*symbols, price=33.5):
    movers = [quote(s, price, 0.12) for s in symbols]
    return FakeMarket(movers, chains={s: chain(s, price) for s in symbols})


class PricedMarket(FakeMarket):
    """Adds live option mids so grading can use the take profit rule."""

    def __init__(self, *a, mids=None, **kw):
        super().__init__(*a, **kw)
        self.mids = mids or {}

    def option_mids(self, symbols):
        return {s: self.mids[s] for s in symbols if s in self.mids}


# Scan persistence


def test_scan_stores_picks_and_run(db, settings):
    run = service.scan(db, market_with("LQDA", "BSP"), RULES, settings, "manual", TODAY)
    assert run.status == "ok" and run.picks == 2 and run.finished_at
    picks = db.query(Pick).all()
    assert {p.symbol for p in picks} == {"LQDA", "BSP"}
    p = picks[0]
    assert p.status == "open" and p.expiry == EXPIRY and p.alert_level == p.short_strike
    assert p.details["csp_contracts"] >= 1 and p.buckets["setup"] == "up_spike"


def test_open_picks_are_not_repeated(db, settings):
    service.scan(db, market_with("LQDA"), RULES, settings, "schedule", TODAY)
    second = service.scan(db, market_with("LQDA"), RULES, settings, "schedule", TODAY)
    assert second.picks == 0
    assert db.query(Pick).count() == 1


def test_scan_errors_are_recorded(db, settings):
    class Broken(FakeMarket):
        def movers(self):
            raise RuntimeError("upstream timeout")

    run = service.scan(db, Broken([]), RULES, settings, "schedule", TODAY)
    assert run.status == "error" and "upstream timeout" in run.error


# Grading


def seeded_pick(db, settings):
    service.scan(db, market_with("LQDA"), RULES, settings, "schedule", TODAY)
    return db.query(Pick).one()


def test_grading_loss_on_close_under_alert(db, settings):
    pick = seeded_pick(db, settings)
    market = FakeMarket([quote("LQDA", pick.short_strike - 1, -0.08)])
    assert service.grade_open_picks(db, market, RULES, date(2026, 10, 16)) == 1
    db.refresh(pick)
    assert pick.status == "loss" and pick.pnl < 0 and "under" in pick.grade_reason


def test_grading_take_profit_uses_option_mids(db, settings):
    pick = seeded_pick(db, settings)
    mids = {pick.short_symbol: 0.30, pick.long_symbol: 0.10}  # spread 0.20 <= half credit
    market = PricedMarket([quote("LQDA", 36, 0.02)], mids=mids)
    service.grade_open_picks(db, market, RULES, date(2026, 10, 20))
    db.refresh(pick)
    assert pick.status == "win" and pick.last_spread_value == 0.2


def test_grading_keeps_open_and_expires_as_win(db, settings):
    pick = seeded_pick(db, settings)
    market = FakeMarket([quote("LQDA", 35, 0.01)])
    service.grade_open_picks(db, market, RULES, date(2026, 10, 20))
    db.refresh(pick)
    assert pick.status == "open" and pick.last_price == 35
    service.grade_open_picks(db, market, RULES, EXPIRY)
    db.refresh(pick)
    assert pick.status == "win" and pick.pnl == pick.est_profit


# Webull connection and token flow


def mock_webull(token_enabled, check_status="NORMAL", create_status="PENDING"):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/openapi/config":
            return httpx.Response(200, json={"token_check_enabled": token_enabled})
        if request.url.path == "/auth/tokens/create":
            return httpx.Response(200, json={"token": "t1", "expires": 1, "status": create_status})
        if request.url.path == "/auth/tokens/check":
            return httpx.Response(200, json={"token": "t1", "status": check_status})
        return httpx.Response(404)

    return handler, calls


@pytest.fixture()
def patch_transport(monkeypatch):
    original = service.WebullClient.__init__  # captured once, so patches don't stack

    def apply(handler):
        def init(self, *a, **kw):
            kw["transport"] = httpx.MockTransport(handler)
            kw["min_interval_s"] = 0
            original(self, *a, **kw)

        monkeypatch.setattr(service.WebullClient, "__init__", init)

    return apply


def creds() -> Settings:
    return Settings(webull_app_key="k", webull_app_secret="s", scheduler_enabled=False)


def test_connect_requires_keys(db):
    with pytest.raises(service.NotConfigured):
        service.connect(Settings(scheduler_enabled=False), db)


def test_connect_without_token_requirement(db, patch_transport):
    handler, calls = mock_webull(token_enabled=False)
    patch_transport(handler)
    service.connect(creds(), db)
    assert calls == ["/openapi/config"]
    assert service.kv_get(db, "webull_token_status") == "NOT_REQUIRED"


def test_token_pending_then_approved(db, patch_transport):
    handler, _ = mock_webull(token_enabled=True, create_status="PENDING", check_status="PENDING")
    patch_transport(handler)
    with pytest.raises(service.TokenPending):
        service.connect(creds(), db)
    assert service.kv_get(db, "webull_token") == "t1"
    assert service.kv_get(db, "webull_token_status") == "PENDING"

    approved, calls = mock_webull(token_enabled=True, check_status="NORMAL")
    patch_transport(approved)
    market = service.connect(creds(), db)
    assert market.client.access_token == "t1"
    assert "/auth/tokens/create" not in calls  # reused the stored token


# Scheduler


def test_parse_times():
    assert [t.hour for t in parse_times("15:55, 10:00")] == [10, 15]


def test_next_job_during_and_after_hours():
    times, grade = parse_times("10:00,11:00"), parse_times("16:15")[0]
    wed_morning = datetime(2026, 10, 14, 9, 0, tzinfo=NY)
    assert next_job(wed_morning, times, grade).at.hour == 10
    wed_noon = datetime(2026, 10, 14, 12, 0, tzinfo=NY)
    job = next_job(wed_noon, times, grade)
    assert (job.kind, job.at.hour, job.at.minute) == ("grade", 16, 15)
    fri_night = datetime(2026, 10, 16, 20, 0, tzinfo=NY)
    job = next_job(fri_night, times, grade)
    assert job.at.date() == date(2026, 10, 19) and job.kind == "scan"  # Monday


# Alerts


def test_alert_message_and_webhook():
    pick = run_scan(market_with("LQDA"), RULES, TODAY).picks[0]
    text = format_pick(pick)
    assert "LQDA" in text and "Spread: sell" in text and "close by Oct 28" in text
    sent = []
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(204))
    )
    assert send_alert("https://hooks.example/x", [pick], client) is True
    assert b"LQDA" in sent[0].content
    assert send_alert(None, [pick]) is False
    failing = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert send_alert("https://hooks.example/x", [pick], failing) is False


# API


def test_api_status_unconfigured(client):
    data = client.get("/api/status").json()
    assert data["configured"] is False
    assert data["last_run"] is None
    assert data["rules"]["max_loss_per_trade"] == 250
    assert client.post("/api/scan").status_code == 503


def test_api_picks_stats_and_runs(client, db, settings):
    service.scan(db, market_with("LQDA", "BSP"), RULES, settings, "manual", TODAY)
    loser = db.query(Pick).filter_by(symbol="BSP").one()
    loser.status, loser.pnl = "loss", -120.0
    db.commit()

    assert [p["symbol"] for p in client.get("/api/picks").json()] == ["LQDA"]
    graded = client.get("/api/picks?status=graded").json()
    assert graded[0]["symbol"] == "BSP" and graded[0]["details"]["csp_contracts"] >= 1
    assert client.get("/api/picks?status=bogus").status_code == 422

    stats = client.get("/api/stats").json()
    assert stats["graded"] == 1 and stats["losses"] == 1 and stats["pnl"] == -120
    assert stats["buckets"]["setup"]["up_spike"]["trades"] == 1
    assert stats["adaptation"]["active"] is False

    runs = client.get("/api/runs").json()
    assert runs[0]["picks"] == 2 and runs[0]["trigger"] == "manual"
    status = client.get("/api/status").json()
    assert status["last_run"]["picks"] == 2


def test_manual_scan_cooldown(client, settings, monkeypatch):
    settings.webull_app_key, settings.webull_app_secret = "k", "s"
    monkeypatch.setattr(api, "run_job", lambda kind, s, trigger: "scan ok: 0 picks")
    api._last_manual["at"] = 0.0
    assert client.post("/api/scan").json() == {"result": "scan ok: 0 picks"}
    assert client.post("/api/scan").status_code == 429


def test_scan_run_model_defaults(db):
    run = ScanRun(trigger="manual")
    db.add(run)
    db.commit()
    assert run.status == "running" and run.rejected == []
