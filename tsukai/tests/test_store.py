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
