import asyncio
import json
from unittest.mock import AsyncMock

import fakeredis.aioredis
import httpx
import jwt
import pytest
from fastapi.testclient import TestClient

from auth import get_current_user
from main import app
from services import cli_auth, cli_session


def token(session_id, user="owner"):
    return jwt.encode(
        {"sub": user, "session_id": session_id},
        "test-signing-key-for-fixtures-only",
        algorithm="HS256",
    )


@pytest.fixture
def auth_http(monkeypatch):
    calls = []
    responses = [
        {"id": "owner", "email": "owner@example.com", "email_confirmed_at": "2026-01-01"},
        {"id": "owner", "hashed_token": "one-time-hash"},
        {
            "access_token": token("cli"),
            "refresh_token": "cli-refresh",
            "expires_in": 3600,
            "user": {"id": "owner"},
        },
    ]

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=responses[len(calls) - 1])

    original = httpx.AsyncClient
    monkeypatch.setattr(
        cli_session.httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )
    monkeypatch.setenv("SUPABASE_URL", "https://auth.example")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "public-key")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "server-key")
    return calls, responses


@pytest.mark.asyncio
async def test_new_session_uses_verified_identity_without_refreshing_browser(auth_http):
    calls, _ = auth_http
    result = await cli_session.create_device_session("owner", token("browser"))
    assert result["refresh_token"] == "cli-refresh"
    assert [r.url.path for r in calls] == [
        "/auth/v1/user",
        "/auth/v1/admin/generate_link",
        "/auth/v1/verify",
    ]
    assert json.loads(calls[1].content) == {"type": "magiclink", "email": "owner@example.com"}
    assert json.loads(calls[2].content) == {"type": "email", "token_hash": "one-time-hash"}
    assert calls[1].headers["authorization"] == "Bearer server-key"
    assert "authorization" not in calls[2].headers


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["wrong_user", "unconfirmed", "mfa"])
async def test_invalid_identity_cannot_mint(auth_http, change):
    calls, responses = auth_http
    if change == "wrong_user":
        responses[0]["id"] = "attacker"
    if change == "unconfirmed":
        responses[0]["email_confirmed_at"] = None
    if change == "mfa":
        responses[0]["factors"] = [{"status": "verified"}]
    with pytest.raises(cli_session.DeviceSessionUnavailable):
        await cli_session.create_device_session("owner", token("browser"))
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_generated_identity_must_match_before_verifying_otp(auth_http):
    calls, responses = auth_http
    responses[1]["id"] = "other-user"
    with pytest.raises(cli_session.DeviceSessionUnavailable):
        await cli_session.create_device_session("owner", token("browser"))
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_browser_session_cannot_be_returned_as_device(auth_http):
    _, responses = auth_http
    responses[2]["access_token"] = token("browser")
    with pytest.raises(cli_session.DeviceSessionUnavailable):
        await cli_session.create_device_session("owner", token("browser"))


@pytest.fixture
def isolated_requests(monkeypatch):
    store = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cli_auth, "_get_redis", lambda: store)
    return store


@pytest.mark.asyncio
async def test_only_one_concurrent_approval_can_mint(isolated_requests):
    request = await cli_auth.create_request("laptop", "mac")
    claims = await asyncio.gather(
        *(cli_auth.claim_authorization(request["request_id"], "owner") for _ in range(2))
    )
    assert sum(c is not None for c in claims) == 1
    nonce = next(c for c in claims if c)
    assert (await cli_auth.consume_by_device_code(request["device_code"]))["status"] == "pending"
    assert not await cli_auth.finish_authorization(
        request["request_id"], "wrong", {"access_token": "bad"}
    )
    assert await cli_auth.finish_authorization(
        request["request_id"], nonce, {"access_token": "new"}
    )
    assert (await cli_auth.consume_by_device_code(request["device_code"]))["tokens"][
        "access_token"
    ] == "new"
    assert (await cli_auth.consume_by_device_code(request["device_code"]))["status"] == "expired"


@pytest.mark.asyncio
async def test_failed_mint_retries_but_denial_prevents_publish(isolated_requests):
    request = await cli_auth.create_request("laptop", "mac")
    nonce = await cli_auth.claim_authorization(request["request_id"], "owner")
    assert await cli_auth.finish_authorization(request["request_id"], nonce, None)
    nonce = await cli_auth.claim_authorization(request["request_id"], "owner")
    assert await cli_auth.deny(request["request_id"])
    assert not await cli_auth.finish_authorization(
        request["request_id"], nonce, {"access_token": "new"}
    )
    assert (await cli_auth.consume_by_device_code(request["device_code"]))["status"] == "denied"


@pytest.fixture
def endpoint(monkeypatch):
    import routes.cli as route

    app.dependency_overrides[get_current_user] = lambda: "owner"
    claim = AsyncMock(return_value="nonce")
    mint = AsyncMock(return_value={"access_token": "cli-access", "refresh_token": "cli-refresh"})
    finish = AsyncMock(return_value=True)
    revoke = AsyncMock()
    monkeypatch.setattr(route.cli_auth, "claim_authorization", claim)
    monkeypatch.setattr(route.cli_auth, "finish_authorization", finish)
    monkeypatch.setattr(route.cli_session, "create_device_session", mint)
    monkeypatch.setattr(route.cli_session, "revoke_device_session", revoke)
    yield TestClient(app), claim, mint, finish, revoke
    app.dependency_overrides.pop(get_current_user, None)


def test_approval_ignores_body_credentials(endpoint):
    client, claim, mint, finish, _ = endpoint
    response = client.post(
        "/api/cli/auth/device/complete",
        headers={"Authorization": "Bearer verified-browser"},
        json={
            "request_id": "request-id",
            "refresh_token": "browser-refresh",
            "email": "attacker@example.com",
        },
    )
    assert response.json() == {"ok": True}
    claim.assert_awaited_once_with("request-id", "owner")
    mint.assert_awaited_once_with("owner", "verified-browser")
    assert finish.await_args.args[2]["refresh_token"] == "cli-refresh"
    assert "cli-refresh" not in response.text


def test_unknown_request_never_mints(endpoint):
    client, claim, mint, _, _ = endpoint
    claim.return_value = None
    response = client.post("/api/cli/auth/device/complete", json={"request_id": "request-id"})
    assert response.status_code == 410
    mint.assert_not_awaited()


def test_provider_failure_is_safe_and_releases_claim(endpoint):
    client, _, mint, finish, _ = endpoint
    mint.side_effect = RuntimeError("private-token-and-provider-body")
    response = client.post(
        "/api/cli/auth/device/complete",
        headers={"Authorization": "Bearer browser"},
        json={"request_id": "request-id"},
    )
    assert response.status_code == 503
    assert "private" not in response.text
    finish.assert_awaited_once_with("request-id", "nonce", None)


def test_denial_during_mint_revokes_only_undelivered_session(endpoint):
    client, _, _, finish, revoke = endpoint
    finish.side_effect = [False, False]
    response = client.post(
        "/api/cli/auth/device/complete",
        headers={"Authorization": "Bearer browser"},
        json={"request_id": "request-id"},
    )
    assert response.status_code == 410
    revoke.assert_awaited_once_with({"access_token": "cli-access", "refresh_token": "cli-refresh"})


def test_mfa_limitation_is_explicit_not_expired_or_generic_retry(endpoint):
    client, _, mint, finish, _ = endpoint
    mint.side_effect = cli_session.DeviceSessionUnsupported("CLI authorization requires MFA login.")
    response = client.post(
        "/api/cli/auth/device/complete",
        headers={"Authorization": "Bearer browser"},
        json={"request_id": "request-id"},
    )
    assert response.status_code == 409
    assert "MFA" in response.json()["detail"]
    finish.assert_awaited_once_with("request-id", "nonce", None)


@pytest.mark.asyncio
async def test_expired_request_cannot_mint_even_if_redis_key_still_exists(isolated_requests):
    request = await cli_auth.create_request("laptop", "mac")
    key = cli_auth._REQ_PREFIX + request["request_id"]
    record = json.loads(await isolated_requests.get(key))
    record["expires_at"] = 1
    await isolated_requests.set(key, json.dumps(record))
    assert await cli_auth.claim_authorization(request["request_id"], "owner") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("after_mint", [False, True])
async def test_cancellation_releases_claim_and_revokes_only_if_minted(endpoint, after_mint):
    from starlette.requests import Request

    import routes.cli as route

    _, _, mint, finish, revoke = endpoint
    if after_mint:
        finish.side_effect = [asyncio.CancelledError(), True]
    else:
        mint.side_effect = asyncio.CancelledError()
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer browser")]})
    with pytest.raises(asyncio.CancelledError):
        await route.device_complete(
            route.DeviceCompleteRequest(request_id="request-id"), request, "owner"
        )
    assert finish.await_args.args == ("request-id", "nonce", None)
    if after_mint:
        revoke.assert_awaited_once_with(
            {"access_token": "cli-access", "refresh_token": "cli-refresh"}
        )
    else:
        revoke.assert_not_awaited()
