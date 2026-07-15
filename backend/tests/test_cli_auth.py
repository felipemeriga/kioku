# backend/tests/test_cli_auth.py
import time
import pytest
import fakeredis.aioredis
import services.cli_auth as ca


@pytest.fixture()
def fake_redis(monkeypatch):
    """Isolate async unit tests from real Redis. NOT applied to HTTP endpoint
    tests (those use the real Redis instance via TestClient)."""
    redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(ca, "_get_redis", lambda: redis_client)
    yield redis_client


def test_hash_is_stable_and_not_plaintext():
    h = ca.hash_device_code("secret-code")
    assert h == ca.hash_device_code("secret-code")
    assert "secret-code" not in h
    assert len(h) == 64  # sha256 hex


@pytest.mark.asyncio
async def test_create_returns_two_secrets(fake_redis):
    r = await ca.create_request("laptop", "darwin")
    assert r["request_id"] and r["device_code"]
    assert r["request_id"] != r["device_code"]
    assert r["expires_in"] == 300


@pytest.mark.asyncio
async def test_info_lookup_hides_secrets(fake_redis):
    r = await ca.create_request("laptop", "darwin")
    rec = await ca.get_by_request_id(r["request_id"])
    assert rec["hostname"] == "laptop"
    assert rec["os"] == "darwin"
    assert rec["status"] == "pending"
    assert "device_code" not in rec  # only the hash is stored


@pytest.mark.asyncio
async def test_authorize_then_consume_delivers_tokens_once(fake_redis):
    r = await ca.create_request("laptop", "darwin")
    ok = await ca.authorize(r["request_id"], {"access_token": "a", "refresh_token": "b"})
    assert ok is True
    first = await ca.consume_by_device_code(r["device_code"])
    assert first["status"] == "authorized"
    assert first["tokens"]["access_token"] == "a"
    second = await ca.consume_by_device_code(r["device_code"])
    assert second["status"] == "expired"  # single-use: gone after delivery


@pytest.mark.asyncio
async def test_pending_then_denied(fake_redis):
    r = await ca.create_request("laptop", "darwin")
    assert (await ca.consume_by_device_code(r["device_code"]))["status"] == "pending"
    await ca.deny(r["request_id"])
    assert (await ca.consume_by_device_code(r["device_code"]))["status"] == "denied"


@pytest.mark.asyncio
async def test_unknown_device_code_is_expired(fake_redis):
    assert (await ca.consume_by_device_code("nope"))["status"] == "expired"


# ---------------------------------------------------------------------------
# Task 2 — HTTP endpoint tests
# ---------------------------------------------------------------------------
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def _start():
    r = client.post("/api/cli/auth/device/start", json={"hostname": "laptop", "os": "darwin"})
    assert r.status_code == 200
    return r.json()


def test_start_returns_verification_url_and_secrets():
    body = _start()
    assert body["request_id"] in body["verification_url"]
    assert "/cli-auth?req=" in body["verification_url"]
    assert body["device_code"]
    assert body["interval"] == 2


def test_info_exposes_only_display_fields():
    body = _start()
    r = client.get(f"/api/cli/auth/device/info?req={body['request_id']}")
    assert r.status_code == 200
    info = r.json()
    assert info["hostname"] == "laptop"
    assert info["valid"] is True
    assert "device_code" not in info and "tokens" not in info


def test_token_poll_pending_returns_428():
    body = _start()
    r = client.post("/api/cli/auth/device/token", json={"device_code": body["device_code"]})
    assert r.status_code == 428


def test_complete_requires_auth():
    body = _start()
    r = client.post("/api/cli/auth/device/complete", json={"request_id": body["request_id"]})
    assert r.status_code in (401, 403)


def test_token_poll_unknown_returns_410():
    r = client.post("/api/cli/auth/device/token", json={"device_code": "bogus-000-nonexistent"})
    assert r.status_code == 410


def test_start_rate_limited_after_burst(monkeypatch):
    import routes.cli as cli_routes
    monkeypatch.setattr(cli_routes, "_DEVICE_RATE_MAX", 3)
    monkeypatch.setattr(cli_routes, "_device_hits", {})
    codes = [
        client.post("/api/cli/auth/device/start", json={"hostname": "h", "os": "o"}).status_code
        for _ in range(5)
    ]
    assert codes.count(429) >= 1  # burst is throttled
