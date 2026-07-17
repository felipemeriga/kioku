"""Low-level HTTP transport to the self-hosted mem0 service.

Thin wrapper over httpx: adds the bearer token, resolves the base URL from
the environment, and enforces a short timeout. Every call raises on non-2xx;
the client layer (`client.py`) catches and degrades to empty/`{"ok": False}`.
"""

from __future__ import annotations

import os

import httpx

_TIMEOUT_S = 5.0
_DEFAULT_URL = "http://mem0:8010"


def _base_url() -> str:
    return os.getenv("MEM0_SERVICE_URL", _DEFAULT_URL).rstrip("/")


def _token() -> str:
    return os.getenv("MEM0_SERVICE_TOKEN", "")


def call(method: str, path: str, json: dict | None = None) -> dict:
    """Make a request to the mem0 service and return the parsed JSON body.

    Raises httpx.HTTPError on transport failure or non-2xx status.
    """
    resp = httpx.request(
        method,
        f"{_base_url()}{path}",
        json=json,
        headers={"Authorization": f"Bearer {_token()}"},
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json() if resp.content else {}
