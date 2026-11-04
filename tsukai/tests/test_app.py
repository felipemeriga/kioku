import asyncio
import hashlib
import json
import time
import uuid
from pathlib import Path

import httpx
import jwt
import pytest

from tsukai.app import create_app
from tsukai.config import Settings
from tsukai.protocol import JobRequest


@pytest.fixture
async def app_client(store, tmp_path):
    settings = Settings(
        service_token="transport-" + "x" * 32,
        capability_key="scope-" + "y" * 32,
        entitled_owners=frozenset({"owner", "other"}),
        auth_probe=False,
        native_bin=str(Path(__file__).parent / "fixtures/native_cli.py"),
        workspace_dir=str(tmp_path),
        drain_seconds=0.1,
        kill_grace_seconds=0.1,
    )
    app = create_app(settings, store)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://fixture"
        ) as client:
            yield app, client, settings


def body(**kw):
    return JobRequest(
        idempotency_key=str(uuid.uuid4()),
        owner_id="owner",
        caller="backend",
        operation="test",
        prompt="answer",
        **kw,
    ).model_dump(mode="json")


def headers(settings, payload, **overrides):
    claims = {
        "iss": "kioku-backend",
        "aud": "tsukai",
        "sub": payload["caller"],
        "owner_id": payload["owner_id"],
        "folder_ids": payload["folder_ids"],
        "profiles": [payload["profile"]],
        "operations": [payload["operation"]],
        "tool_allowlist": payload["tool_allowlist"],
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "jti": str(uuid.uuid4()),
        "ai_depth": payload["ai_depth"],
        "parent_job_id": payload["parent_job_id"],
        "root_job_id": payload["root_job_id"],
        "request_sha256": hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        **overrides,
    }
    return {
        "Authorization": "Bearer " + settings.service_token,
        "X-Tsukai-Capability": jwt.encode(claims, settings.capability_key, algorithm="HS256"),
    }


async def terminal(client, path, auth):
    for _ in range(100):
        result = await client.get(path, headers=auth)
        assert result.status_code == 200, result.text
        if result.json()["status"] not in {"running", "queued"}:
            return result.json()
        await asyncio.sleep(0.02)
    raise AssertionError("job never terminated")


async def test_admission_replay_result_ack_and_disconnect_independence(app_client):
    _, client, settings = app_client
    payload = body()
    auth = headers(settings, payload)
    a, b = await asyncio.gather(
        client.post("/v1/jobs", json=payload, headers=auth),
        client.post("/v1/jobs", json=payload, headers=auth),
    )
    assert a.status_code == b.status_code == 202
    assert a.json()["job_id"] == b.json()["job_id"]
    job = a.json()
    # No browser subscribed; accepted inference completes regardless.
    result = await terminal(client, job["result_url"], auth)
    assert result["status"] == "completed"
    assert result["result"]["text"] == "Canonical answer."
    assert result["result"]["attempt_id"]
    assert result["request_sha256"]
    stream = await client.get(job["events_url"], headers=auth)
    assert "event: job.completed" in stream.text
    assert "private-diagnostic" not in stream.text
    assert "event: text.delta" in stream.text
    replay = await client.get(job["events_url"], headers={**auth, "Last-Event-ID": "2"})
    assert "id: 1\n" not in replay.text
    assert (
        await client.post(
            f"/v1/jobs/{job['job_id']}/ack",
            headers=auth,
            json={"consumer": "backend", "reference": "message"},
        )
    ).status_code == 200
    assert (await client.get("/v1/jobs?unacknowledged=true", headers=auth)).json()["jobs"] == []


async def test_capability_digest_owner_model_and_tool_rejections(app_client):
    _, client, settings = app_client
    payload = body()
    auth = headers(settings, payload)
    assert (
        await client.post("/v1/jobs", json={**payload, "prompt": "tampered"}, headers=auth)
    ).status_code == 403
    assert (
        await client.post(
            "/v1/jobs", json=payload, headers=headers(settings, payload, sub="mihari")
        )
    ).status_code == 403
    assert (
        await client.post(
            "/v1/jobs", json=payload, headers=headers(settings, payload, owner_id="other")
        )
    ).status_code == 403
    assert (
        await client.post(
            "/v1/jobs", json=payload, headers=headers(settings, payload, exp=int(time.time()) - 1)
        )
    ).status_code == 403
    bad = {**payload, "model": "haiku"}
    assert (
        await client.post("/v1/jobs", json=bad, headers=headers(settings, bad))
    ).status_code == 422
    bad = {**payload, "tool_allowlist": ["Bash"], "tool_capability_ref": "caller-ref"}
    assert (
        await client.post("/v1/jobs", json=bad, headers=headers(settings, bad))
    ).status_code == 422


async def test_invalid_schema_repairs_fresh_once(app_client):
    _, client, settings = app_client
    payload = body(
        response_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        }
    )
    payload["prompt"] = "INVALID"
    auth = headers(settings, payload)
    submitted = (await client.post("/v1/jobs", json=payload, headers=auth)).json()
    result = await terminal(client, submitted["result_url"], auth)
    assert result["status"] == "completed"
    events = (await client.get(submitted["events_url"], headers=auth)).text
    frames = [json.loads(line[6:]) for line in events.splitlines() if line.startswith("data: ")]
    starts = [event["data"] for event in frames if event["type"] == "attempt.started"]
    assert len(starts) == 2
    assert starts[0]["native_session_id"] != starts[1]["native_session_id"]
    assert all(not event["resume"] for event in starts)


async def test_auth_circuit_and_drain_remain_live(app_client):
    app, client, settings = app_client
    payload = body()
    payload["prompt"] = "AUTH"
    auth = headers(settings, payload)
    submitted = (await client.post("/v1/jobs", json=payload, headers=auth)).json()
    result = await terminal(client, submitted["result_url"], auth)
    assert result["error"]["code"] == "reauth_required"
    assert (await client.get("/health/live")).status_code == 200
    assert (await client.get("/health/ready")).status_code == 503
    assert (await client.post("/v1/jobs", json=payload, headers=auth)).status_code == 503
    await app.state.scheduler.drain()
    assert (await client.get("/health/live")).status_code == 200


async def test_explicit_auth_recheck_singleflight_and_no_health_inference(app_client):
    app, client, settings = app_client
    settings.auth_probe = True
    app.state.scheduler.auth_state = "reauth_required"
    auth = {"Authorization": "Bearer " + settings.service_token}
    a, b = await asyncio.gather(
        client.post("/internal/recheck-auth", headers=auth),
        client.post("/internal/recheck-auth", headers=auth),
    )
    assert a.status_code == b.status_code == 200
    assert app.state.scheduler.auth_state == "ready"
    from sqlalchemy import func, select

    from tsukai.tables import jobs

    async with app.state.scheduler.store.engine.connect() as conn:
        before = (await conn.execute(select(func.count()).select_from(jobs))).scalar_one()
    for _ in range(5):
        assert (await client.get("/health/ready")).status_code == 200
    async with app.state.scheduler.store.engine.connect() as conn:
        after = (await conn.execute(select(func.count()).select_from(jobs))).scalar_one()
    assert before == after == 1


async def test_transient_startup_database_failure_recovers(store, tmp_path, monkeypatch):
    original = store.ping
    calls = 0

    async def transient():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("fixture database unavailable")
        await original()

    monkeypatch.setattr(store, "ping", transient)
    settings = Settings(
        service_token="x" * 32,
        capability_key="y" * 32,
        auth_probe=False,
        entitled_owners=frozenset({"owner"}),
        workspace_dir=str(tmp_path),
        native_bin=str(Path(__file__).parent / "fixtures/native_cli.py"),
    )
    app = create_app(settings, store)
    async with app.router.lifespan_context(app):
        assert app.state.scheduler.auth_state == "dependency_unavailable"
        app.state.scheduler._next_dependency_probe = 0
        app.state.scheduler.wake.set()
        for _ in range(100):
            if app.state.scheduler.auth_state == "ready":
                break
            await asyncio.sleep(0.02)
        assert app.state.scheduler.auth_state == "ready"
