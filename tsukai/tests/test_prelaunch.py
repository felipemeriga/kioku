"""Grant retries stop at the CLI launch boundary and preserve safe session reuse."""

import asyncio
import time
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from tsukai.config import Settings
from tsukai.protocol import JobRequest
from tsukai.scheduler import Scheduler
from tsukai.tables import attempts


def request():
    return JobRequest(
        idempotency_key=str(uuid.uuid4()),
        owner_id="owner",
        caller="backend",
        operation="test",
        profile="chat",
        conversation_id="conversation",
        prompt="never leak this prompt",
        folder_ids=["folder"],
        tool_allowlist=["knowledge_base_search"],
        tool_capability_ref="turn",
    )


def settings(tmp_path):
    return Settings(
        service_token="secret",
        backend_url="http://backend",
        workspace_dir=str(tmp_path),
        heartbeat_seconds=100,
    )


@pytest.mark.parametrize("failure", ["timeout", 429, 503, 401, 403])
async def test_only_transient_prelaunch_grants_retry_then_launch_once(
    store, tmp_path, monkeypatch, failure
):
    req = request()
    job = await store.admit(req)
    claim = await store.claim("worker")
    native = AsyncMock()
    native.run.return_value = {"text": "ok", "usage": {}}
    scheduler = Scheduler(store, settings(tmp_path), native)
    calls = []

    async def post(self, url, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("sensitive credentials must not persist")
            return httpx.Response(failure)
        return httpx.Response(200, json={"mcp_url": "http://backend/mcp", "capability": "opaque"})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    await scheduler.execute(claim)
    state = await store.get(job["id"])
    if failure in (401, 403):
        assert len(calls) == 1
        native.run.assert_not_called()
        assert state["status"] == "failed"
        assert state["error"] == {
            "code": "tool_capability_denied",
            "usage_complete": False,
            "native_started": False,
        }
    else:
        assert len(calls) == 2 and calls[0] == calls[1]
        native.run.assert_awaited_once()
        assert state["status"] == "completed"


@pytest.mark.parametrize("resumed", [False, True])
async def test_exhausted_prelaunch_transport_never_invokes_native_or_quarantines_session(
    store, tmp_path, monkeypatch, resumed
):
    req = request()
    if resumed:
        await store.admit(req)
        seed = await store.claim("worker")
        await store.finish(seed["attempt"], "completed", result={"text": "seed", "usage": {}})
        req = req.model_copy(update={"idempotency_key": str(uuid.uuid4())})
    job = await store.admit(req)
    claim = await store.claim("worker")
    native = AsyncMock()
    scheduler = Scheduler(store, settings(tmp_path), native)

    async def post(self, *args, **kwargs):
        raise httpx.ReadTimeout("secret/private/prompt")

    post_mock = AsyncMock(side_effect=post)
    monkeypatch.setattr(httpx.AsyncClient, "post", post_mock)
    await scheduler.execute(claim)
    state = await store.get(job["id"])
    assert state["status"] == "failed"
    assert state["error"]["code"] == "tool_backend_unavailable"
    assert state["error"]["native_started"] is False
    native.run.assert_not_called()
    assert post_mock.await_count == 3
    async with store.engine.connect() as conn:
        diagnostic = (
            await conn.execute(
                select(attempts.c.diagnostic).where(attempts.c.id == claim["attempt"]["id"])
            )
        ).scalar_one()
    assert diagnostic == {
        "stage": "tool_capability",
        "native_started": False,
        "exception_type": "ReadTimeout",
    }
    # A new user turn remains admissible without rebuilding a healthy old transcript.
    await store.admit(req.model_copy(update={"idempotency_key": str(uuid.uuid4())}))
    next_claim = await store.claim("worker")
    assert next_claim["attempt"]["resume"] is resumed


async def test_total_grant_budget_includes_waiting_and_no_native_on_expiry(tmp_path):
    scheduler = Scheduler(None, settings(tmp_path), AsyncMock())
    claim = {"job": {"id": "job"}, "attempt": {"id": "attempt", "deadline": time.time() + 0.05}}

    async def post(*args, **kwargs):
        await asyncio.sleep(1)

    from unittest.mock import patch

    from tsukai.validation import NativeError

    started = time.monotonic()
    with patch.object(httpx.AsyncClient, "post", post):
        with pytest.raises(NativeError, match="tool_backend_unavailable"):
            await scheduler.tool_config(claim, request())
    assert time.monotonic() - started < 0.3
    scheduler.native.run.assert_not_called()


async def test_postlaunch_unknown_failure_never_retries_grant_or_native(
    store, tmp_path, monkeypatch
):
    job = await store.admit(request())
    claim = await store.claim("worker")
    native = AsyncMock()
    native.run.side_effect = RuntimeError("private content")
    scheduler = Scheduler(store, settings(tmp_path), native)
    post = AsyncMock(
        return_value=httpx.Response(
            200, json={"mcp_url": "http://backend/mcp", "capability": "opaque"}
        )
    )
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    await scheduler.execute(claim)
    assert post.await_count == 1
    native.run.assert_awaited_once()
    state = await store.get(job["id"])
    assert state["status"] == "uncertain"
    assert state["error"]["requires_explicit_recovery"] is True


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b'{"mcp_url":42}',
        b'{"mcp_url":"http://foreign/mcp","capability":"secret"}',
    ],
)
async def test_malformed_grant_response_is_typed_prelaunch_failure(
    store, tmp_path, monkeypatch, body
):
    job = await store.admit(request())
    claim = await store.claim("worker")
    native = AsyncMock()
    scheduler = Scheduler(store, settings(tmp_path), native)
    post = AsyncMock(return_value=httpx.Response(200, content=body))
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    await scheduler.execute(claim)
    state = await store.get(job["id"])
    assert state["status"] == "failed"
    assert state["error"] == {
        "code": "invalid_tool_backend",
        "usage_complete": False,
        "native_started": False,
    }
    assert post.await_count == 1
    native.run.assert_not_called()
