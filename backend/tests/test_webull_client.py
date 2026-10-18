import json
from datetime import UTC, datetime

import httpx
import pytest

from app.webull.client import WebullClient, WebullError, _rows
from app.webull.signing import sign_request

FIXED = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)


# Expected values were produced by the official webull-openapi-python-sdk
# (webull.core.auth.composer.default_signature_composer.calc_signature) with
# the same timestamp, nonce, key and secret.
@pytest.mark.parametrize(
    ("path", "query", "body", "expected"),
    [
        (
            "/market-data/stocks/snapshots/list",
            {"symbols": "Z,BSP", "category": "US_STOCK"},
            None,
            "tSh1D6M8tp2MmKGTZzMA0pSkr8wWDV5USgFj+LynEH0=",
        ),
        (
            "/market-data/stocks/bars/list",
            None,
            {"symbols": ["Z"], "category": "US_STOCK", "timespan": "D", "count": "30"},
            "loWCEXg7JatmMNCeRLB4QPu/sYd4Ri14TAu02ePU6Ko=",
        ),
    ],
)
def test_signature_matches_official_sdk(path, query, body, expected):
    headers = sign_request(
        host="api.webull.com",
        path=path,
        app_key="test-app-key",
        app_secret="test-app-secret",
        query=query,
        body=body,
        now=FIXED,
        nonce="nonce-123",
    )
    assert headers["x-signature"] == expected
    assert headers["x-signature-algorithm"] == "HMAC-SHA256"
    assert headers["x-timestamp"] == "2026-10-18T12:00:00Z"


def test_signature_changes_with_secret():
    kw = dict(host="h", path="/p", app_key="k", now=FIXED, nonce="n")
    assert (
        sign_request(app_secret="a", **kw)["x-signature"]
        != sign_request(app_secret="b", **kw)["x-signature"]
    )


def make_client(handler) -> WebullClient:
    return WebullClient(
        "key", "secret", environment="sandbox", transport=httpx.MockTransport(handler),
        min_interval_s=0,
    )  # fmt: skip


def test_requests_are_signed_and_routed_to_sandbox():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=[{"symbol": "Z", "price": "30.82"}])

    client = make_client(handler)
    rows = client.stock_snapshots(["Z"])
    req = seen[0]
    assert req.url.host == "api.sandbox.webull.com"
    assert req.url.path == "/market-data/stocks/snapshots/list"
    assert req.url.params["category"] == "US_STOCK"
    assert req.headers["x-app-key"] == "key"
    assert req.headers["x-version"] == "v3"
    assert req.headers["x-signature"]
    assert "x-access-token" not in req.headers
    assert rows == [{"symbol": "Z", "price": "30.82"}]


def test_access_token_header_and_body_post():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={"result": [{"symbol": "Z", "result": [{"close": "30.82"}]}]},
        )

    client = make_client(handler)
    client.access_token = "tok"
    bars = client.daily_bars(["Z"], count=5)
    assert bars == {"Z": [{"close": "30.82"}]}
    assert seen[0].headers["x-access-token"] == "tok"
    assert json.loads(seen[0].content) == {
        "symbols": ["Z"],
        "category": "US_STOCK",
        "timespan": "D",
        "count": "5",
    }


def test_snapshot_batches_of_100_and_option_batches_of_20():
    calls = []

    def handler(request):
        calls.append(request.url.params["symbols"].count(",") + 1)
        return httpx.Response(200, json=[])

    client = make_client(handler)
    client.stock_snapshots([f"S{i}" for i in range(150)])
    client.option_snapshots([f"O{i}" for i in range(45)])
    assert calls == [100, 50, 20, 20, 5]


def test_errors_raise_with_message():
    client = make_client(lambda r: httpx.Response(401, json={"message": "invalid app key"}))
    with pytest.raises(WebullError, match="invalid app key") as exc:
        client.earnings_calendar("Z")
    assert exc.value.status == 401


def test_contract_pagination_is_bounded():
    def handler(request):
        return httpx.Response(200, json={"data": [{"symbol": "X"}], "pagination_key": "more"})

    assert len(make_client(handler).put_contracts("Z", "2026-11-01", 20, 30)) == 5


def test_rows_unwraps_known_shapes():
    assert _rows([1]) == [1]
    assert _rows({"data": [2]}) == [2]
    assert _rows({"result": [3]}) == [3]
    assert _rows({"nothing": 1}) == []
    assert _rows(None) == []
