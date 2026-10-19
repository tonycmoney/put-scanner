"""Fill a local database by running the real scan and grading pipeline against the
simulated market used by the test suite. Used to render README screenshots
without live market data.

    cd backend && DATABASE_URL=sqlite:///./sim.db python ../scripts/simulate.py
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import service  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Pick  # noqa: E402
from tests.fakes import EXPIRY, TODAY, FakeMarket, chain, falling_bars, quote  # noqa: E402

settings = get_settings()
rules = settings.rules()
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)


def scan_on(db, today, movers, spy, expiry, bars=None):
    chains = {q.symbol: chain(q.symbol, q.price, expiry) for q in movers}
    market = FakeMarket(movers, chains=chains, spy_change=spy, bars=bars or {})
    return service.scan(db, market, rules, settings, "schedule", today)


def grade_on(db, today, closes):
    market = FakeMarket([quote(s, px, 0.0) for s, px in closes.items()])
    return service.grade_open_picks(db, market, rules, today)


with SessionLocal() as db:
    # Two weeks ago: four setups, graded at expiry.
    earlier = TODAY - timedelta(days=21)
    earlier_expiry = earlier + timedelta(days=16)
    scan_on(
        db,
        earlier,
        [
            quote("RKLB", 31.2, 0.14, name="Rocket Lab"),
            quote("HIMS", 44.8, -0.09, name="Hims & Hers Health"),
            quote("SOFI", 18.4, 0.11, name="SoFi Technologies", volume=40_000_000, cap=20e9),
            quote("CELH", 27.9, -0.12, name="Celsius Holdings"),
        ],
        0.004,
        earlier_expiry,
    )
    grade_on(db, earlier_expiry, {"RKLB": 33.0, "HIMS": 46.1, "SOFI": 15.2, "CELH": 29.4})

    # Today: open setups plus movers the rules reject.
    scan_on(
        db,
        TODAY,
        [
            quote("LQDA", 33.5, 0.12, name="Liquidia"),
            quote("ACHR", 22.6, 0.17, name="Archer Aviation", volume=25_000_000, cap=6e9),
            quote("BSP", 38.2, -0.08, name="Bluestone Partners"),
            quote("PENNY", 4.1, 0.31, name="Penny Pharma"),
            quote("KNIFE", 25.0, -0.15, name="Knife Corp"),
            quote("THIN", 28.0, 0.09, volume=120_000, name="Thin Volume Inc"),
        ],
        0.002,
        EXPIRY,
        bars={"KNIFE": falling_bars(25.0)},
    )
    print("simulated picks:", db.query(Pick).count(), "on", date.today())
