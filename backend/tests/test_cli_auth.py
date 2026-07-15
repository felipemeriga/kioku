# backend/tests/test_cli_auth.py
import time
import pytest
import fakeredis.aioredis
import services.cli_auth as ca


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(ca, "_get_redis", lambda: client)
    yield client


def test_hash_is_stable_and_not_plaintext():
    h = ca.hash_device_code("secret-code")
    assert h == ca.hash_device_code("secret-code")
    assert "secret-code" not in h
    assert len(h) == 64  # sha256 hex


@pytest.mark.asyncio
async def test_create_returns_two_secrets():
    r = await ca.create_request("laptop", "darwin")
    assert r["request_id"] and r["device_code"]
    assert r["request_id"] != r["device_code"]
    assert r["expires_in"] == 300


@pytest.mark.asyncio
async def test_info_lookup_hides_secrets():
    r = await ca.create_request("laptop", "darwin")
    rec = await ca.get_by_request_id(r["request_id"])
    assert rec["hostname"] == "laptop"
    assert rec["os"] == "darwin"
    assert rec["status"] == "pending"
    assert "device_code" not in rec  # only the hash is stored


@pytest.mark.asyncio
async def test_authorize_then_consume_delivers_tokens_once():
    r = await ca.create_request("laptop", "darwin")
    ok = await ca.authorize(r["request_id"], {"access_token": "a", "refresh_token": "b"})
    assert ok is True
    first = await ca.consume_by_device_code(r["device_code"])
    assert first["status"] == "authorized"
    assert first["tokens"]["access_token"] == "a"
    second = await ca.consume_by_device_code(r["device_code"])
    assert second["status"] == "expired"  # single-use: gone after delivery


@pytest.mark.asyncio
async def test_pending_then_denied():
    r = await ca.create_request("laptop", "darwin")
    assert (await ca.consume_by_device_code(r["device_code"]))["status"] == "pending"
    await ca.deny(r["request_id"])
    assert (await ca.consume_by_device_code(r["device_code"]))["status"] == "denied"


@pytest.mark.asyncio
async def test_unknown_device_code_is_expired():
    assert (await ca.consume_by_device_code("nope"))["status"] == "expired"
