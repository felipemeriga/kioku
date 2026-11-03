"""Slow maintenance I/O must not stop the API event loop."""

import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from routes import mihari


@pytest.mark.asyncio
async def test_slow_mihari_git_request_does_not_stall_health(monkeypatch):
    app = FastAPI()
    app.include_router(mihari.router, prefix="/api/mihari")

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    class Query:
        def table(self, *_args):
            return self

        select = eq = limit = table

        def execute(self):
            return SimpleNamespace(
                data=[
                    {"private_key_encrypted": "test", "public_key": "test", "fingerprint": "test"}
                ]
            )

    def slow_remote(*_args):
        time.sleep(0.35)
        return None, "simulated remote timeout"

    monkeypatch.setattr(mihari, "_api_key_auth", lambda _: ("user", "scope", "key"))
    monkeypatch.setattr(mihari, "get_supabase", Query)
    monkeypatch.setattr(mihari, "decrypt_secret", lambda _: "private-test-key")
    monkeypatch.setattr(mihari, "_ls_remote_with_key", slow_remote)
    ticks = []
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def probes():
            for _ in range(12):
                ticks.append(time.monotonic())
                assert (await client.get("/api/health")).status_code == 200
                await asyncio.sleep(0.04)

        async def maintenance():
            await asyncio.sleep(0.02)
            response = await client.post(
                "/api/mihari/test-access", json={"remote_url": "git@example.com:test/repo.git"}
            )
            assert response.status_code == 200

        await asyncio.gather(probes(), maintenance())
    assert max(b - a for a, b in zip(ticks, ticks[1:])) < 0.2
