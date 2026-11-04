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


@pytest.mark.parametrize("prompt", ["TEXT_EOF", "NONZERO", "FOREIGN_INIT", "MISSING_FINAL_ID"])
async def test_uncertain_native_outcomes_quarantine_chat_without_retry(app_client, prompt):
    _, client, settings = app_client
    payload = body(profile="chat", conversation_id="uncertain")
    payload["prompt"] = prompt
    auth = headers(settings, payload)
    submitted = (await client.post("/v1/jobs", json=payload, headers=auth)).json()
    result = await terminal(client, submitted["result_url"], auth)
    assert result["status"] == "uncertain"
    if prompt == "NONZERO":
        assert result["result"]["text"] == "Canonical answer."
        assert result["result"]["usage"]["list_equivalent_usd"] == 0.001
    payload["idempotency_key"] = str(uuid.uuid4())
    assert (
        await client.post("/v1/jobs", json=payload, headers=headers(settings, payload))
    ).status_code == 409
    usage = (await client.get(f"/v1/jobs/{submitted['job_id']}/usage", headers=auth)).json()
    assert len(usage["attempts"]) == 1


async def test_repair_keeps_private_schema_errors_and_both_attempt_costs(app_client):
    app, client, settings = app_client
    payload = body(
        response_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        }
    )
    payload["prompt"] = "INVALID"
    auth = headers(settings, payload)
    submitted = (await client.post("/v1/jobs", json=payload, headers=auth)).json()
    assert (await terminal(client, submitted["result_url"], auth))["status"] == "completed"
    usage = (await client.get(f"/v1/jobs/{submitted['job_id']}/usage", headers=auth)).json()
    assert len(usage["attempts"]) == 2
    assert [row["usage"]["list_equivalent_usd"] for row in usage["attempts"]] == [0.001, 0.001]
    from sqlalchemy import select

    from tsukai.tables import attempts

    async with app.state.scheduler.store.engine.connect() as conn:
        diagnostic = (
            await conn.execute(
                select(attempts.c.diagnostic).where(
                    attempts.c.job_id == submitted["job_id"], attempts.c.number == 1
                )
            )
        ).scalar_one()
    assert diagnostic["invalid_response"] == {"answer": 17}
    assert diagnostic["validation_errors"][0]["path"] == ["answer"]
    assert diagnostic["validation_errors"][0]["validator"] == "type"
    assert "invalid_response" not in json.dumps(usage)


def deletion_headers(settings, payload, operation, profiles):
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    claims = {
        "iss": "kioku-backend",
        "aud": "tsukai",
        "sub": "backend",
        "owner_id": payload["owner_id"],
        "folder_ids": [],
        "operations": [operation],
        "profiles": profiles,
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "jti": str(uuid.uuid4()),
        "request_sha256": digest,
    }
    return {
        "Authorization": "Bearer " + settings.service_token,
        "X-Tsukai-Capability": jwt.encode(claims, settings.capability_key, algorithm="HS256"),
    }


async def test_signed_conversation_deletion_reaps_then_removes_artifacts(
    app_client, tmp_path, monkeypatch
):
    app, client, settings = app_client
    payload = body(profile="chat", conversation_id="delete-me")
    payload["prompt"] = "SLEEP"
    auth = headers(settings, payload)
    submitted = (await client.post("/v1/jobs", json=payload, headers=auth)).json()
    store = app.state.scheduler.store
    for _ in range(100):
        if app.state.scheduler.native.processes:
            break
        await asyncio.sleep(0.02)
    from sqlalchemy import select

    from tsukai.tables import sessions

    async with store.engine.connect() as conn:
        session = (await conn.execute(select(sessions))).mappings().one()
    native = tmp_path / "native-state"
    project = native / "projects" / ("-workspaces-chat-" + session["native_session_id"])
    project.mkdir(parents=True)
    (project / (session["native_session_id"] + ".jsonl")).write_text("private transcript")
    (project / "sessions-index.json").write_text("private native index")
    credential = native / ".credentials.json"
    credential.write_text("fixture credential must survive")
    unrelated = native / "projects" / "unrelated.jsonl"
    unrelated.write_text("other conversation")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(native))
    deletion_body = {
        "owner_id": "owner",
        "conversation_id": "delete-me",
        "action": "delete_conversation",
    }
    cleanup_auth = deletion_headers(settings, deletion_body, "session.delete", ["chat"])
    bad = await client.post(
        "/v1/conversations/delete-me/delete",
        json={**deletion_body, "owner_id": "other"},
        headers=cleanup_auth,
    )
    assert bad.status_code == 403
    response = await client.post(
        "/v1/conversations/delete-me/delete", json=deletion_body, headers=cleanup_auth
    )
    assert response.status_code == 202
    deletion_id = response.json()["deletion_id"]
    for _ in range(100):
        state = await client.get(f"/v1/deletions/{deletion_id}", headers=cleanup_auth)
        if state.json()["status"] == "cleaned":
            break
        await asyncio.sleep(0.02)
    assert state.json()["status"] == "cleaned"
    assert not app.state.scheduler.native.processes
    assert not Path(session["workspace"]).exists() and not project.exists()
    assert credential.exists() and unrelated.exists()
    assert await store.get(submitted["job_id"]) is None
    payload["idempotency_key"] = str(uuid.uuid4())
    assert (
        await client.post("/v1/jobs", json=payload, headers=headers(settings, payload))
    ).status_code == 409
    repeated = await client.post(
        "/v1/conversations/delete-me/delete", json=deletion_body, headers=cleanup_auth
    )
    assert repeated.json() == {"deletion_id": deletion_id, "status": "cleaned"}


async def test_account_cleanup_survives_owner_deentitlement_and_blocks_all_new_work(app_client):
    app, client, settings = app_client
    payload = body()
    auth = headers(settings, payload)
    submitted = (await client.post("/v1/jobs", json=payload, headers=auth)).json()
    await terminal(client, submitted["result_url"], auth)
    settings.entitled_owners = frozenset()
    payload_delete = {"owner_id": "owner", "action": "delete_account"}
    cleanup_auth = deletion_headers(settings, payload_delete, "account.delete", [])
    deleted = await client.post("/v1/account/delete", json=payload_delete, headers=cleanup_auth)
    assert deleted.status_code == 202
    deletion_id = deleted.json()["deletion_id"]
    for _ in range(100):
        state = await client.get(f"/v1/deletions/{deletion_id}", headers=cleanup_auth)
        if state.json()["status"] == "cleaned":
            break
        await asyncio.sleep(0.02)
    assert state.json()["status"] == "cleaned"
    settings.entitled_owners = frozenset({"owner"})
    payload["idempotency_key"] = str(uuid.uuid4())
    assert (
        await client.post("/v1/jobs", json=payload, headers=headers(settings, payload))
    ).status_code == 409


async def test_admin_lists_only_active_sessions_and_forbids_owner_capabilities(app_client):
    app, client, settings = app_client
    idle = body(profile="chat", conversation_id="idle")
    idle_auth = headers(settings, idle)
    completed = (await client.post("/v1/jobs", json=idle, headers=idle_auth)).json()
    await terminal(client, completed["result_url"], idle_auth)
    payload = body(profile="chat", conversation_id="active")
    payload["prompt"] = "SLEEP"
    normal = headers(settings, payload)
    submitted = (await client.post("/v1/jobs", json=payload, headers=normal)).json()
    for _ in range(100):
        if app.state.scheduler.native.processes:
            break
        await asyncio.sleep(0.02)
    assert (await client.get("/v1/admin/active-sessions", headers=normal)).status_code == 403
    admin = headers(
        settings,
        payload,
        admin=True,
        operations=["runtime.sessions.read"],
        profiles=[],
        folder_ids=[],
        tool_allowlist=[],
    )
    response = await client.get("/v1/admin/active-sessions", headers=admin)
    assert response.status_code == 200
    active = response.json()["sessions"]
    assert len(active) == 1
    assert active[0]["job_id"] == submitted["job_id"]
    assert active[0]["conversation_id"] == "active" and active[0]["native_session_id"]
    assert active[0]["state"] == "running" and active[0]["pid"] is not None
    assert active[0]["owner_id"] == "owner" and active[0]["elapsed_seconds"] >= 0
    for forbidden in ("prompt", "workspace", "environment", "headers", "SLEEP"):
        assert forbidden not in json.dumps(response.json())
    # A read-only admin grant grants no inference permission, even with admin=true.
    assert (await client.post("/v1/jobs", json=payload, headers=admin)).status_code == 403
    await client.post(f"/v1/jobs/{submitted['job_id']}/cancel", headers=normal)


async def test_usage_exposes_observed_native_timings_without_invented_browser_latency(app_client):
    _, client, settings = app_client
    payload = body()
    auth = headers(settings, payload)
    submitted = (await client.post("/v1/jobs", json=payload, headers=auth)).json()
    await terminal(client, submitted["result_url"], auth)
    response = await client.get(f"/v1/jobs/{submitted['job_id']}/usage", headers=auth)
    attempt = response.json()["attempts"][0]
    assert attempt["started_at"] and attempt["finished_at"]
    assert attempt["first_event_at"] and attempt["first_text_at"]
    assert (
        0
        <= attempt["first_event_seconds"]
        <= attempt["first_text_seconds"]
        <= attempt["elapsed_seconds"]
    )
    assert attempt["queue_wait_seconds"] >= 0
    assert "browser" not in json.dumps(attempt)


async def test_abnormal_invalid_completion_never_launches_repair(app_client):
    _, client, settings = app_client
    payload = body(
        response_schema={
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
        }
    )
    payload["prompt"] = "NONZERO INVALID"
    auth = headers(settings, payload)
    submitted = (await client.post("/v1/jobs", json=payload, headers=auth)).json()
    result = await terminal(client, submitted["result_url"], auth)
    assert result["status"] == "uncertain"
    usage = (await client.get(f"/v1/jobs/{submitted['job_id']}/usage", headers=auth)).json()
    assert len(usage["attempts"]) == 1
    assert not usage["attempts"][0]["usage"]["complete"]
    assert result["result"]["structured"] == {"answer": 17}


async def test_app_owned_store_uses_configured_workspace_root(tmp_path):
    from tsukai.lifecycle import remove_artifacts

    custom_root = tmp_path / "custom-runtime-root"
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path}/owned-store.db",
        workspace_dir=str(custom_root),
    )
    app = create_app(settings)
    store = app.state.scheduler.store
    try:
        await store.create_test_schema()
        await store.admit(JobRequest.model_validate(body()))
        claim = await store.claim("fixture")
        workspace = Path(claim["workspace"])
        assert custom_root in workspace.parents
        workspace.mkdir(parents=True)
        (workspace / "private-spool").write_text("fixture")
        remove_artifacts(
            {
                "artifacts": [
                    {
                        "workspace": str(workspace),
                        "native_session_id": claim["attempt"]["native_session_id"],
                    }
                ]
            },
            settings.workspace_dir,
            str(tmp_path / "native-state"),
        )
        assert not workspace.exists()
    finally:
        await store.engine.dispose()
