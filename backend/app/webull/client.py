"""Minimal, read only Webull OpenAPI client for the endpoints the scanner needs.

Deliberately has no order placement methods: the scanner alerts, it never trades.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.webull.signing import compact_json, sign_request

log = logging.getLogger("webull")

HOSTS = {
    "production": "api.webull.com",
    "sandbox": "api.sandbox.webull.com",
}


class WebullError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Webull API {status}: {message}")
        self.status = status


class WebullClient:
    def __init__(
        self,
        app_key: str,
        app_secret: str,
        *,
        environment: str = "sandbox",
        host: str | None = None,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
        min_interval_s: float = 0.15,
    ) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.host = host or HOSTS[environment]
        self.access_token: str | None = None
        self._min_interval = min_interval_s
        self._last_call = 0.0
        self._http = httpx.Client(
            base_url=f"https://{self.host}",
            timeout=timeout,
            transport=transport,
            headers={"Accept": "application/json", "x-webull-client-source": "put-scanner"},
        )

    # Low level

    def _request(
        self,
        method: str,
        path: str,
        *,
        query: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        version: str = "v3",
    ) -> Any:
        # Stay well under per second rate limits.
        wait = self._min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

        query = {k: str(v) for k, v in (query or {}).items() if v is not None}
        headers = sign_request(
            host=self.host,
            path=path,
            app_key=self.app_key,
            app_secret=self.app_secret,
            query=query,
            body=body,
        )
        headers["x-version"] = version
        if self.access_token:
            headers["x-access-token"] = self.access_token
        content = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            content = compact_json(body).encode()

        response = self._http.request(method, path, params=query, content=content, headers=headers)
        if response.status_code >= 400:
            message = response.text[:300]
            try:
                data = response.json()
                message = data.get("message") or data.get("msg") or message
            except ValueError:
                pass
            raise WebullError(response.status_code, message)
        return response.json() if response.content else None

    # Access token (only required when the account has token checks enabled)

    def token_required(self) -> bool:
        data = self._request("GET", "/openapi/config")
        return bool((data or {}).get("token_check_enabled", False))

    def create_token(self) -> dict:
        """Start a token request; the user approves it in the Webull app."""
        return self._request("POST", "/auth/tokens/create", body={})

    def check_token(self, token: str) -> dict:
        return self._request("POST", "/auth/tokens/check", body={"token": token})

    # Market data

    def stock_snapshots(self, symbols: list[str]) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(symbols), 100):
            chunk = ",".join(symbols[i : i + 100])
            data = self._request(
                "GET",
                "/market-data/stocks/snapshots/list",
                query={"symbols": chunk, "category": "US_STOCK"},
            )
            out.extend(_rows(data))
        return out

    def daily_bars(self, symbols: list[str], count: int = 30) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for i in range(0, len(symbols), 20):
            data = self._request(
                "POST",
                "/market-data/stocks/bars/list",
                body={
                    "symbols": symbols[i : i + 20],
                    "category": "US_STOCK",
                    "timespan": "D",
                    "count": str(count),
                },
            )
            for item in _rows(data):
                out[item.get("symbol", "")] = item.get("result") or []
        return out

    def gainers_losers(self, direction: str) -> list[dict]:
        """direction='DESC' for gainers, 'ASC' for losers (top 200, one day)."""
        data = self._request(
            "GET",
            "/market-data/screeners/gainers-losers/list",
            query={
                "rank_type": "DAY_1",
                "category": "US_STOCK",
                "sort_by": "CHANGE_RATIO",
                "direction": direction,
            },
        )
        return _rows(data)

    def earnings_calendar(self, symbol: str) -> list[dict]:
        data = self._request(
            "GET",
            "/market-data/fundamentals/earnings-calendars/list",
            query={"symbol": symbol, "category": "US_STOCK"},
        )
        return _rows(data)

    def put_contracts(
        self, symbol: str, expiry_on_or_after: str, strike_min: float, strike_max: float
    ) -> list[dict]:
        """Listed puts expiring on or after a date, within a strike range.

        Per the API docs `end_date` is the expiration lower bound; callers
        apply any upper bound themselves.
        """
        rows: list[dict] = []
        pagination_key = None
        for _ in range(5):  # bounded pagination
            data = self._request(
                "GET",
                "/trading/instruments/options/contracts/list",
                query={
                    "category": "US_OPTION",
                    "underlying_symbols": symbol,
                    "option_type": "PUT",
                    "end_date": expiry_on_or_after,
                    "strike_price_gte": f"{strike_min:.2f}",
                    "strike_price_lte": f"{strike_max:.2f}",
                    "pagination_key": pagination_key,
                },
            )
            rows.extend(_rows(data))
            pagination_key = data.get("pagination_key") if isinstance(data, dict) else None
            if not pagination_key:
                break
        return rows

    def option_snapshots(self, option_symbols: list[str]) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(option_symbols), 20):
            data = self._request(
                "GET",
                "/market-data/options/snapshots/list",
                query={"symbols": ",".join(option_symbols[i : i + 20]), "category": "US_OPTION"},
            )
            out.extend(_rows(data))
        return out

    def close(self) -> None:
        self._http.close()


def _rows(data: Any) -> list[dict]:
    """Webull wraps lists differently per endpoint: bare list, {data: [...]}, {result: [...]}."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("data", "result", "list", "contracts", "items"):
            if isinstance(data.get(key), list):
                return data[key]
    return []
