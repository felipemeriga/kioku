import asyncio
import time

import pytest
from sqlalchemy import update

from tsukai.protocol import JobRequest
from tsukai.store import Conflict, Fenced, Store
from tsukai.tables import attempts


def request(**kw):
    import uuid

    return JobRequest(
        idempotency_key=str(uuid.uuid4()),
        owner_id="owner",
        caller="backend",
        **({"operation": "test", "prompt": "Answer from supplied evidence."} | kw),
    )


async def test_concurrent_idempotency_and_payload_conflict(store):
    req = request()
    a, b = await asyncio.gather(store.admit(req), store.admit(req))
    assert a["id"] == b["id"]
    assert len(await store.replay(a["id"])) == 1
    with pytest.raises(Conflict, match="idempotency"):
        await store.admit(req.model_copy(update={"prompt": "different"}))


async def test_conversation_lock_and_resume_mapping(store):
    req = request(profile="chat", conversation_id="conversation")
    job = await store.admit(req)
    with pytest.raises(Conflict, match="conversation_busy"):
        await store.admit(request(profile="chat", conversation_id="conversation"))
    claim = await store.claim("worker")
    first = claim["attempt"]
    assert not first["resume"]
    await store.finish(first, "completed", result={"text": "ok", "usage": {}})
    await store.admit(request(profile="chat", conversation_id="conversation"))
    second = (await store.claim("worker"))["attempt"]
    assert second["resume"] and second["native_session_id"] == first["native_session_id"]
    assert (await store.get(job["id"]))["status"] == "completed"


async def test_fencing_crash_recovery_and_no_blind_retry(store):
    job = await store.admit(request(profile="chat", conversation_id="lost"))
    claim = await store.claim("dead-worker")
    attempt = claim["attempt"]
    async with store.transaction() as conn:
        await conn.execute(
            update(attempts)
            .where(attempts.c.id == attempt["id"])
            .values(lease_until=time.time() - 1)
        )
    assert await store.recover() == 1
    with pytest.raises(Fenced):
        await store.append(attempt, "text.delta", {"text": "stale"})
    state = await store.get(job["id"])
    assert state["status"] == "uncertain"
    assert await store.claim("new-worker") is None
    with pytest.raises(Conflict, match="needs_rebuild"):
        await store.admit(request(profile="chat", conversation_id="lost"))


async def test_durable_replay_and_ack(store):
    job = await store.admit(request())
    claim = await store.claim("worker")
    await store.append(claim["attempt"], "text.delta", {"text": "provisional"})
    await store.finish(claim["attempt"], "completed", result={"text": "canonical", "usage": {}})
    other = Store(store.engine.url.render_as_string(hide_password=False))
    try:
        replay = await other.replay(job["id"])
        assert [x["seq"] for x in replay] == list(range(1, len(replay) + 1))
        assert replay[-1]["data"]["result"]["text"] == "canonical"
        assert await other.replay(job["id"], replay[-2]["seq"]) == replay[-1:]
        await other.acknowledge(job["id"], "backend", "message-1")
        await other.acknowledge(job["id"], "backend", "message-1")
        with pytest.raises(Conflict, match="ack_reference"):
            await other.acknowledge(job["id"], "backend", "message-2")
    finally:
        await other.engine.dispose()


async def test_fresh_repair_and_metadata_reserved_lane(store):
    roots = []
    for i in range(2):
        job = await store.admit(request(profile="chat", conversation_id=f"root{i}"))
        roots.append((job, await store.claim("worker")))
    await store.admit(request())
    assert await store.claim("worker") is None
    child = request(
        profile="metadata_child",
        ai_depth=1,
        operation="text_to_sql",
        parent_job_id=roots[0][0]["id"],
        root_job_id=roots[0][0]["id"],
    )
    await store.admit(child)
    child_claim = await store.claim("worker")
    assert child_claim["job"]["profile"] == "metadata_child"
    await store.finish(
        child_claim["attempt"], "failed", error={"code": "invalid_structured_output"}, retry=True
    )
    repair = await store.claim("worker")
    assert repair["attempt"]["native_session_id"] != child_claim["attempt"]["native_session_id"]
    assert not repair["attempt"]["resume"]


async def test_cancel_queued_and_running(store):
    queued = await store.admit(request())
    await store.cancel(queued["id"])
    assert (await store.get(queued["id"]))["status"] == "cancelled"
    running = await store.admit(request())
    claim = await store.claim("worker")
    await store.cancel(running["id"])
    assert await store.heartbeat(claim["attempt"])
    await store.finish(claim["attempt"], "completed", result={"text": "late", "usage": {}})
    assert (await store.get(running["id"]))["status"] == "cancelled"


async def test_postgres_runtime_role_is_scoped(store):
    if store.engine.dialect.name != "postgresql":
        pytest.skip("real PostgreSQL restricted-role acceptance runs in CI")
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    async with store.engine.connect() as conn:
        role = (
            await conn.execute(
                text("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user")
            )
        ).one()
        assert not role.rolsuper and not role.rolbypassrls
        with pytest.raises(DBAPIError):
            await conn.execute(text("SELECT * FROM public.tsukai_fixture_domain_secret"))


async def test_explicit_rebuild_changes_generation_and_policy(store):
    await store.admit(request(profile="chat", conversation_id="rebuild"))
    first = await store.claim("worker")
    await store.finish(first["attempt"], "cancelled", error={"code": "cancelled"})
    rebuilt = request(
        profile="chat",
        conversation_id="rebuild",
        rebuild_from_committed_history=True,
        system_prompt="version2",
    )
    await store.admit(rebuilt)
    second = await store.claim("worker")
    assert second["attempt"]["native_session_id"] != first["attempt"]["native_session_id"]
    assert not second["attempt"]["resume"]
    await store.finish(second["attempt"], "completed", result={"text": "rebuilt", "usage": {}})
    with pytest.raises(Conflict, match="policy_changed"):
        await store.admit(
            request(profile="chat", conversation_id="rebuild", system_prompt="version3")
        )
    await store.admit(request(profile="chat", conversation_id="rebuild", system_prompt="version2"))
    third = await store.claim("worker")
    assert third["attempt"]["resume"]
    assert third["attempt"]["native_session_id"] == second["attempt"]["native_session_id"]


async def test_two_postgres_workers_share_admission_and_claim_fence(store):
    if store.engine.dialect.name != "postgresql":
        pytest.skip("distributed PostgreSQL lock acceptance runs in CI")
    other = Store(store.engine.url.render_as_string(hide_password=False))
    try:
        req = request()
        first, second = await asyncio.gather(store.admit(req), other.admit(req))
        assert first["id"] == second["id"]
        claims = await asyncio.gather(store.claim("one"), other.claim("two"))
        assert sum(c is not None for c in claims) == 1
    finally:
        await other.engine.dispose()


async def test_expire_queued_deadline_independent_of_full_process_slots(store):
    roots = []
    for i in range(2):
        job = await store.admit(request(profile="chat", conversation_id=f"busy{i}"))
        roots.append(job)
        await store.claim("worker")
    child = request(
        profile="metadata_child",
        ai_depth=1,
        operation="text_to_sql",
        parent_job_id=roots[0]["id"],
        root_job_id=roots[0]["id"],
    )
    await store.admit(child)
    await store.claim("worker")
    waiting = await store.admit(request(profile="chat", conversation_id="deadline"))
    from tsukai.tables import jobs

    async with store.transaction() as conn:
        await conn.execute(
            update(jobs).where(jobs.c.id == waiting["id"]).values(queue_deadline=time.time() - 1)
        )
    assert await store.expire_queued() == 1
    assert (await store.get(waiting["id"]))["error"]["code"] == "queue_timeout"
    assert await store.claim("worker") is None
    # Expiring an unstarted turn releases its conversation admission lock.
    await store.admit(request(profile="chat", conversation_id="deadline"))


async def test_three_chat_burst_waits_for_root_slot_without_borrowing_child_lane(
    store, monkeypatch
):
    clock = time.time()
    monkeypatch.setattr("tsukai.store.time.time", lambda: clock)
    roots = []
    for i in range(2):
        await store.admit(request(profile="chat", conversation_id=f"burst{i}"))
        roots.append(await store.claim("worker"))
    waiting = await store.admit(request(profile="chat", conversation_id="burst2"))
    assert waiting["queue_deadline"] - waiting["created_at"] == 330
    assert await store.claim("worker") is None

    # Both normal roots may legitimately execute beyond the old30s queue limit.
    clock += 29
    for root in roots:
        await store.heartbeat(root["attempt"])
    clock += 2
    assert await store.expire_queued() == 0
    assert await store.claim("worker") is None
    child = await store.admit(
        request(
            profile="metadata_child",
            ai_depth=1,
            operation="text_to_sql",
            parent_job_id=roots[0]["job"]["id"],
            root_job_id=roots[0]["job"]["id"],
        )
    )
    child_claim = await store.claim("worker")
    assert child_claim["job"]["id"] == child["id"]
    assert await store.claim("worker") is None
    await store.finish(roots[1]["attempt"], "completed", result={"text": "ok", "usage": {}})
    third = await store.claim("worker")
    assert third["job"]["id"] == waiting["id"]
    assert third["attempt"]["deadline"] - clock == 300


async def test_chat_queue_has_absolute_expiry_and_background_bound_is_unchanged(store, monkeypatch):
    clock = time.time()
    monkeypatch.setattr("tsukai.store.time.time", lambda: clock)
    chat = await store.admit(request(profile="chat", conversation_id="bounded"))
    background = await store.admit(request())
    assert background["queue_deadline"] - background["created_at"] == 1800
    clock += 329
    assert await store.expire_queued() == 0
    clock += 2
    assert await store.expire_queued() == 1
    assert (await store.get(chat["id"]))["error"]["code"] == "queue_timeout"
    assert (await store.get(background["id"]))["status"] == "queued"
    await store.admit(request(profile="chat", conversation_id="bounded"))


async def test_fairness_chat_priority_aging_and_actual_maintenance_caller(store):
    from tsukai.tables import jobs

    completed = await store.admit(request())
    first = await store.claim("worker")
    await store.finish(first["attempt"], "completed", result={"text": "ok", "usage": {}})
    a = await store.admit(request())
    b = await store.admit(request().model_copy(update={"owner_id": "other"}))
    picked = await store.claim("worker")
    assert picked["job"]["id"] == b["id"]  # Least recently served owner wins same aged class.
    await store.finish(picked["attempt"], "completed", result={"text": "ok", "usage": {}})
    chat = await store.admit(request(profile="chat", conversation_id="priority"))
    picked = await store.claim("worker")
    assert picked["job"]["id"] == chat["id"]
    await store.finish(picked["attempt"], "completed", result={"text": "ok", "usage": {}})
    async with store.transaction() as conn:
        await conn.execute(
            update(jobs).where(jobs.c.id == a["id"]).values(created_at=time.time() - 121)
        )
    await store.admit(request(profile="chat", conversation_id="new-chat"))
    picked = await store.claim("worker")
    assert picked["job"]["id"] == a["id"]  # Two-minute-old completion outranks new chat.
    maintenance = await store.admit(
        request().model_copy(update={"owner_id": "maint", "caller": "mihari"})
    )
    picked_maintenance = await store.claim("worker")
    assert picked_maintenance["job"]["id"] == maintenance["id"]
    assert (await store.get(completed["id"]))["status"] == "completed"


async def test_private_diagnostic_retention_preserves_usage(store):
    from sqlalchemy import select

    from tsukai.tables import jobs

    job = await store.admit(request())
    claim = await store.claim("worker")
    usage = {"list_equivalent_usd": 0.123, "complete": True}
    await store.finish(
        claim["attempt"],
        "failed",
        result={"text": "", "usage": usage},
        error={"code": "invalid_structured_output"},
        diagnostic={"invalid_response": "private evidence"},
    )
    async with store.transaction() as conn:
        old = time.time() - 31 * 86400
        await conn.execute(
            update(attempts).where(attempts.c.id == claim["attempt"]["id"]).values(finished_at=old)
        )
        await conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(updated_at=old))
    await store.prune()
    async with store.engine.connect() as conn:
        row = (
            (await conn.execute(select(attempts).where(attempts.c.id == claim["attempt"]["id"])))
            .mappings()
            .one()
        )
        assert row["diagnostic"] is None and row["usage"] == usage
    assert (await store.get(job["id"]))["request"]["prompt"] == "[expired diagnostic evidence]"
