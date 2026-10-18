"""Webull OpenAPI request signing (HMAC-SHA256).

A dependency free reimplementation of the scheme used by the official
`webull-openapi-python-sdk` (webull/core/auth/composer). The tests check it
against signatures produced by the SDK itself.

String to sign:
    url_quote( path + "&" + join(sorted("k=v" for signing headers + query))
               [ + "&" + UPPER(sha256_hex(compact_json(body))) ] )
Signature:
    base64( hmac_sha256(app_secret + "&", string_to_sign) )
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

SIGN_ALGORITHM = "HMAC-SHA256"
SIGN_VERSION = "1.0"


def timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def compact_json(body: Any) -> str:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def string_to_sign(path: str, sign_params: dict[str, str], body: Any | None = None) -> str:
    pairs = "&".join(f"{k}={v}" for k, v in sorted(sign_params.items()))
    text = f"{path}&{pairs}" if path else pairs
    if body is not None:
        text += "&" + hashlib.sha256(compact_json(body).encode()).hexdigest().upper()
    return quote(text, safe="")


def sign_request(
    *,
    host: str,
    path: str,
    app_key: str,
    app_secret: str,
    query: dict[str, Any] | None = None,
    body: Any | None = None,
    now: datetime | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    """Return the headers to send (x-app-key, x-timestamp, ..., x-signature)."""
    headers = {
        "x-app-key": app_key,
        "x-timestamp": timestamp(now),
        "x-signature-version": SIGN_VERSION,
        "x-signature-algorithm": SIGN_ALGORITHM,
        "x-signature-nonce": nonce or str(uuid.uuid4()),
    }
    sign_params = {k.lower(): v for k, v in headers.items()}
    sign_params["host"] = host
    for key, value in (query or {}).items():
        existing = sign_params.get(key)
        sign_params[key] = f"{existing}&{value}" if existing is not None else str(value)

    digest = hmac.new(
        (app_secret + "&").encode(),
        string_to_sign(path, sign_params, body).encode(),
        hashlib.sha256,
    ).digest()
    headers["x-signature"] = base64.b64encode(digest).decode().strip()
    return headers
