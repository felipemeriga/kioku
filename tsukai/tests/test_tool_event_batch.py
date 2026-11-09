"""Completion evidence remains ordered and fenced when persisted as one batch."""

import time

import httpx
import pytest
from sqlalchemy import update
from test_app import body, headers

from tsukai.app import create_app
from tsukai.config import Settings
from tsukai.protocol import JobRequest
from tsukai.store import Fenced
from tsukai.tables import attempts


@pytest.fixture
async def batch_context(store):
    settings = Settings(
        service_token="service-" + "x" * 32,
        capability_key="scope-" + "y" * 32,
        entitled_owners=frozenset({"owner", "other"}),
        auth_probe=False,
    )
    payload = body(profile="chat", conversation_id="conversation", folder_ids=["folder"])
    job = await store.admit(JobRequest.model_validate(payload))
    claim = await store.claim("worker")
    app = create_app(settings, store)
    # No scheduler/native process is started; exercise real HTTP authorization and SQL.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://fixture"
    ) as client:
        yield client, settings, payload, job, claim["attempt"]


def completion_pair(attempt):
    return {
        "attempt_id": attempt["id"],
        "events": [
            {"type": "retrieval.completed", "data": {"result_ref": "durable-artifact"}},
            {"type": "tool.completed", "data": {"result_ref": "durable-artifact"}},
        ],
    }


async def test_http_completion_pair_persists_both_ordered_events(batch_context, store):
    client, settings, payload, job, attempt = batch_context
    response = await client.post(
        f"/v1/jobs/{job['id']}/tool-events/batch",
        headers=headers(settings, payload),
        json=completion_pair(attempt),
    )
    assert response.status_code == 200
    events = await store.replay(job["id"])
    assert [item["type"] for item in events[-2:]] == ["retrieval.completed", "tool.completed"]
    assert [item["seq"] for item in events] == list(range(1, len(events) + 1))
    assert all(item["data"]["result_ref"] == "durable-artifact" for item in events[-2:])


@pytest.mark.parametrize(
    "reason,status",
    [("owner", 404), ("scope", 403), ("caller", 403), ("deleted", 410), ("fenced", 409)],
)
async def test_batch_retains_live_authorization_and_fencing(batch_context, store, reason, status):
    client, settings, payload, job, attempt = batch_context
    overrides = {}
    if reason == "owner":
        overrides["owner_id"] = "other"
    elif reason == "scope":
        overrides["folder_ids"] = ["foreign"]
    elif reason == "caller":
        overrides["sub"] = "mihari"
    elif reason == "deleted":
        await store.begin_deletion("owner", "conversation")
    elif reason == "fenced":
        async with store.transaction() as conn:
            await conn.execute(
                update(attempts)
                .where(attempts.c.id == attempt["id"])
                .values(lease_until=time.time() - 1)
            )
    before = await store.replay(job["id"])
    response = await client.post(
        f"/v1/jobs/{job['id']}/tool-events/batch",
        headers=headers(settings, payload, **overrides),
        json=completion_pair(attempt),
    )
    assert response.status_code == status
    assert await store.replay(job["id"]) == before
    assert "durable-artifact" not in response.text


@pytest.mark.parametrize("reason,status", [("reverse", 403), ("extra", 422), ("oversized", 413)])
async def test_batch_is_bounded_and_only_accepts_the_completion_pair(
    batch_context, store, reason, status
):
    client, settings, payload, job, attempt = batch_context
    value = completion_pair(attempt)
    if reason == "reverse":
        value["events"].reverse()
    elif reason == "extra":
        value["events"].append(value["events"][-1])
    else:
        value["events"][0]["data"] = {"text": "x" * 65537}
    before = await store.replay(job["id"])
    response = await client.post(
        f"/v1/jobs/{job['id']}/tool-events/batch",
        headers=headers(settings, payload),
        json=value,
    )
    assert response.status_code == status
    assert await store.replay(job["id"]) == before


async def test_second_event_failure_rolls_back_the_whole_batch(batch_context, store, monkeypatch):
    _, _, _, job, attempt = batch_context
    before = await store.replay(job["id"])
    if store.engine.dialect.name == "postgresql":
        from sqlalchemy.exc import IntegrityError

        # The second row violates NOT NULL after the same statement reserved both
        # sequence numbers; PostgreSQL must roll back the reservation and both rows.
        with pytest.raises(IntegrityError):
            await store.tool_events(
                job["id"], attempt["id"], [("retrieval.completed", {}), (None, {})]
            )
        assert await store.replay(job["id"]) == before
        await store.tool_events(job["id"], attempt["id"], [("tool.completed", {})])
        replay = await store.replay(job["id"])
        assert replay[-1]["seq"] == before[-1]["seq"] + 1
    else:
        original = store._event
        calls = 0

        async def interrupted(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("injected persistence interruption")
            return await original(*args, **kwargs)

        monkeypatch.setattr(store, "_event", interrupted)
        before = await store.replay(job["id"])
        with pytest.raises(RuntimeError, match="interruption"):
            await store.tool_events(
                job["id"], attempt["id"], [("retrieval.completed", {}), ("tool.completed", {})]
            )
        assert await store.replay(job["id"]) == before
        monkeypatch.setattr(store, "_event", original)
    with pytest.raises(Fenced, match="unknown_attempt"):
        await store.tool_events("foreign-job", attempt["id"], [("tool.completed", {})])


async def test_active_attempt_endpoint_keeps_live_scope_and_revocation_checks(batch_context, store):
    client, settings, payload, job, attempt = batch_context
    path = f"/v1/jobs/{job['id']}/attempts/{attempt['id']}"
    response = await client.get(path, headers=headers(settings, payload))
    assert response.status_code == 200 and response.json()["active"] is True
    assert (
        await client.get(path, headers=headers(settings, payload, owner_id="other"))
    ).status_code == 404
    assert (
        await client.get(path, headers=headers(settings, payload, folder_ids=["foreign"]))
    ).status_code == 403
    await store.begin_deletion("owner", "conversation")
    assert (await client.get(path, headers=headers(settings, payload))).status_code == 410


async def test_pg_tool_event_pair_is_one_ordered_write_statement(batch_context, store):
    from sqlalchemy import event

    if store.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL atomic event CTE")
    _, _, _, job, attempt = batch_context
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(store.engine.sync_engine, "before_cursor_execute", capture)
    try:
        await store.tool_events(
            job["id"],
            attempt["id"],
            [("retrieval.completed", {"text": "雪"}), ("tool.completed", {"ok": True})],
        )
    finally:
        event.remove(store.engine.sync_engine, "before_cursor_execute", capture)
    writes = [sql for sql in statements if "INSERT INTO tsukai_events" in sql]
    assert len(writes) == 1 and "tool_event_sequences AS" in writes[0]
    assert not any(sql.startswith("UPDATE tsukai_jobs") for sql in statements)
    replay = (await store.replay(job["id"]))[-2:]
    assert [row["type"] for row in replay] == ["retrieval.completed", "tool.completed"]
    assert [row["data"] for row in replay] == [{"text": "雪"}, {"ok": True}]
    assert replay[0]["seq"] + 1 == replay[1]["seq"]
    assert replay[0]["created_at"] <= replay[1]["created_at"]


@pytest.mark.parametrize("parent_change", [{"status": "completed"}, {"cancel_requested": True}])
async def test_tool_event_batch_rejects_inactive_metadata_parent(store, parent_change):
    from test_store import request

    from tsukai.tables import jobs

    parent = await store.admit(request(profile="chat", conversation_id="parent"))
    await store.claim("worker")
    child = await store.admit(
        request(
            profile="metadata_child",
            ai_depth=1,
            operation="text_to_sql",
            parent_job_id=parent["id"],
            root_job_id=parent["id"],
        )
    )
    attempt = (await store.claim("worker"))["attempt"]
    async with store.transaction() as conn:
        await conn.execute(update(jobs).where(jobs.c.id == parent["id"]).values(**parent_change))
    before = await store.replay(child["id"])
    with pytest.raises(Fenced, match="metadata_parent_inactive"):
        await store.tool_events(
            child["id"],
            attempt["id"],
            [
                ("retrieval.completed", {}),
                ("tool.completed", {}),
            ],
        )
    assert await store.replay(child["id"]) == before
