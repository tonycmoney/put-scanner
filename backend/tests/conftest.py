import os
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = (
    os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{Path(_tmp) / 'test.db'}"
)
os.environ["SCHEDULER_ENABLED"] = "false"

from fastapi.testclient import TestClient  # noqa: E402

from app.config import Settings, get_settings  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        yield session


@pytest.fixture()
def settings():
    return Settings(database_url=os.environ["DATABASE_URL"], scheduler_enabled=False)


@pytest.fixture()
def client(db, settings):
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
