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
        child_claim["attempt"],
        "failed",
        error={"code": "invalid_structured_output"},
        retry=True,
        diagnostic={"validation_error": "required field missing"},
    )
    repair = await store.claim("worker")
    assert repair["attempt"]["native_session_id"] != child_claim["attempt"]["native_session_id"]
    assert not repair["attempt"]["resume"]
    assert repair["repair_diagnostic"] == {"validation_error": "required field missing"}


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


@pytest.mark.parametrize("operation", ["rag_agent", "rag_agent_sonnet"])
async def test_plain_chat_keeps_fresh_profile_with_absolute_interactive_queue_bound(
    store, monkeypatch, operation
):
    clock = time.time()
    monkeypatch.setattr("tsukai.store.time.time", lambda: clock)
    plain = await store.admit(request(profile="completion", operation=operation))
    background = await store.admit(request(operation="contextual"))
    assert plain["profile"] == "completion" and plain["conversation_id"] is None
    assert plain["queue_deadline"] - plain["created_at"] == 330
    assert background["queue_deadline"] - background["created_at"] == 1800
    clock += 329
    assert await store.expire_queued() == 0
    clock += 2
    assert await store.expire_queued() == 1
    assert (await store.get(plain["id"]))["error"]["code"] == "queue_timeout"
    assert (await store.get(background["id"]))["status"] == "queued"


@pytest.mark.parametrize(
    "caller,operation,interactive",
    [
        ("backend", "rag_agent", True),
        ("backend", "rag_agent_sonnet", True),
        ("mcp", "rag_agent", False),
        ("mcp", "rag_agent_sonnet", False),
        ("mihari", "rag_agent", False),
        ("mihari", "rag_agent_sonnet", False),
        ("backend", "contextual", False),
        ("backend", "query_rewrite", False),
    ],
)
async def test_only_registered_backend_plain_chat_gets_interactive_priority(
    store, monkeypatch, caller, operation, interactive
):
    clock = time.time()
    monkeypatch.setattr("tsukai.store.time.time", lambda: clock)
    background = await store.admit(request(operation="folder_summary_doc"))
    clock += 1
    candidate = await store.admit(
        request(operation=operation).model_copy(update={"caller": caller})
    )
    assert candidate["queue_deadline"] - candidate["created_at"] == (330 if interactive else 1800)
    chosen = await store.claim("worker")
    assert chosen["job"]["id"] == (candidate if interactive else background)["id"]
    if interactive:
        assert not chosen["attempt"]["resume"]
        assert chosen["job"]["profile"] == "completion"


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


async def test_pinned_cli_upgrade_requires_explicit_rebuild_of_existing_native_mapping(
    store, monkeypatch
):
    import tsukai.store as store_module

    req = request(profile="chat", conversation_id="versioned")
    with monkeypatch.context() as old:
        old.setattr(store_module, "NATIVE_VERSION", "2.1.285")
        await store.admit(req)
        seed = await store.claim("old-worker")
        await store.finish(seed["attempt"], "completed", result={"text": "old", "usage": {}})
    import uuid

    next_turn = req.model_copy(update={"idempotency_key": str(uuid.uuid4())})
    with pytest.raises(Conflict, match="conversation_policy_changed"):
        await store.admit(next_turn)
    rebuilt = next_turn.model_copy(
        update={"idempotency_key": str(uuid.uuid4()), "rebuild_from_committed_history": True}
    )
    await store.admit(rebuilt)
    claim = await store.claim("new-worker")
    assert not claim["attempt"]["resume"]


@pytest.mark.parametrize(
    "caller,operation,budget",
    [
        ("mihari", "mihari.documentation", 600),
        ("mihari", "mihari.reground", 600),
        ("mihari", "mihari.activity", 300),
        ("backend", "mihari.documentation", 300),
    ],
)
async def test_only_heavy_mihari_jobs_receive_longer_execution_deadline(
    store, caller, operation, budget
):
    req = request(operation=operation).model_copy(update={"caller": caller})
    await store.admit(req)
    claimed = await store.claim("worker")
    assert claimed["attempt"]["deadline"] - claimed["attempt"]["started_at"] == budget


async def test_effort_can_change_per_turn_without_losing_resume_but_cannot_change_on_retry(store):
    req = request(profile="chat", conversation_id="effort", reasoning_effort="low")
    await store.admit(req)
    with pytest.raises(Conflict, match="idempotency"):
        await store.admit(req.model_copy(update={"reasoning_effort": "high"}))
    first = (await store.claim("worker"))["attempt"]
    await store.finish(first, "completed", result={"text": "ok", "usage": {}})
    await store.admit(request(profile="chat", conversation_id="effort", reasoning_effort="high"))
    second = (await store.claim("worker"))["attempt"]
    assert second["resume"]
    assert second["native_session_id"] == first["native_session_id"]


async def test_idle_claim_does_not_scan_active_jobs_or_owner_history(store):
    """Idle dispatcher ticks must release the shared admission lock promptly."""
    from sqlalchemy import event

    statements = []

    def record_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(store._read_engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        assert await store.claim("idle-worker") is None
    finally:
        event.remove(store._read_engine.sync_engine, "before_cursor_execute", record_statement)
    reads = [statement for statement in statements if "FROM tsukai_jobs" in statement]
    assert len(reads) == 1
    assert "tsukai_attempts" not in reads[0]


async def test_dispatch_recovers_expired_lease_before_claim_and_fences_old_writer(store):
    from tsukai.tables import jobs

    roots = []
    for _ in range(2):
        await store.admit(request())
        roots.append((await store.claim("lost-worker"))["attempt"])
    waiting = await store.admit(request())
    async with store.transaction() as conn:
        await conn.execute(
            update(attempts).where(attempts.c.id == roots[0]["id"]).values(lease_until=0)
        )
        await conn.execute(
            update(jobs).where(jobs.c.id == waiting["id"]).values(queue_deadline=time.time() + 30)
        )
    claims = await store.dispatch("new-worker")
    assert [claim["job"]["id"] for claim in claims] == [waiting["id"]]
    assert (await store.get(roots[0]["job_id"]))["status"] == "uncertain"
    with pytest.raises(Fenced):
        await store.append(roots[0], "text.delta", {"text": "stale"})


async def test_dispatch_rollback_keeps_expiry_recovery_and_claim_atomic(store, monkeypatch):
    from tsukai.tables import jobs

    running = await store.admit(request())
    attempt = (await store.claim("lost-worker"))["attempt"]
    expired = await store.admit(request())
    async with store.transaction() as conn:
        await conn.execute(
            update(attempts).where(attempts.c.id == attempt["id"]).values(lease_until=0)
        )
        await conn.execute(update(jobs).where(jobs.c.id == expired["id"]).values(queue_deadline=0))

    async def fail_claim(*args):
        raise RuntimeError("injected dispatch failure")

    monkeypatch.setattr(store, "_claim", fail_claim)
    with pytest.raises(RuntimeError, match="injected"):
        await store.dispatch("worker")
    assert (await store.get(running["id"]))["status"] == "running"
    assert (await store.get(expired["id"]))["status"] == "queued"
    assert [event["type"] for event in await store.replay(running["id"])] == [
        "job.queued",
        "attempt.started",
    ]


async def test_dispatch_without_capacity_still_expires_queue(store):
    from tsukai.tables import jobs

    expired = await store.admit(request())
    async with store.transaction() as conn:
        await conn.execute(update(jobs).where(jobs.c.id == expired["id"]).values(queue_deadline=0))
    assert await store.dispatch("worker", capacity=0) == []
    assert (await store.get(expired["id"]))["status"] == "failed"


async def test_idle_dispatch_only_reads_and_never_takes_the_global_write_lock(store):
    from sqlalchemy import event

    transactions, statements = [], []

    def record_begin(conn):
        transactions.append(True)

    def record_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(store._read_engine.sync_engine, "begin", record_begin)
    event.listen(store._read_engine.sync_engine, "before_cursor_execute", record_statement)
    try:
        assert await store.dispatch("idle-worker") == []
    finally:
        event.remove(store._read_engine.sync_engine, "begin", record_begin)
        event.remove(store._read_engine.sync_engine, "before_cursor_execute", record_statement)
    assert len(transactions) == 1
    assert len(statements) == 1
    assert "pg_advisory" not in statements[0]


async def test_event_sequence_reservation_rolls_back_without_replay_gap(store):
    job = await store.admit(request())
    attempt = (await store.claim("worker"))["attempt"]
    before = await store.replay(job["id"])
    with pytest.raises(RuntimeError, match="interrupted"):
        async with store.transaction() as conn:
            await store._event(
                conn, job["id"], "text.delta", {"text": "not committed"}, attempt["id"]
            )
            raise RuntimeError("interrupted")
    assert await store.replay(job["id"]) == before
    await store.append(attempt, "text.delta", {"text": "durable"})
    replay = await store.replay(job["id"])
    assert [item["seq"] for item in replay] == list(range(1, len(replay) + 1))
    assert replay[-1]["data"] == {"text": "durable"}


async def test_dispatch_negative_snapshot_cannot_lose_a_racing_admission(store, monkeypatch):
    original = store.dispatch_needed
    admitted = []

    async def admission_after_snapshot():
        needed = await original()
        assert needed is False
        admitted.append(await store.admit(request()))
        return needed

    monkeypatch.setattr(store, "dispatch_needed", admission_after_snapshot)
    assert await store.dispatch("worker") == []
    assert (await store.get(admitted[0]["id"]))["status"] == "queued"
    monkeypatch.setattr(store, "dispatch_needed", original)
    assert [claim["job"]["id"] for claim in await store.dispatch("worker")] == [admitted[0]["id"]]


async def test_dispatch_positive_snapshot_rechecks_cancelled_work_under_lock(store, monkeypatch):
    job = await store.admit(request())
    original = store.dispatch_needed

    async def cancellation_after_snapshot():
        assert await original() is True
        await store.cancel(job["id"])
        return True

    monkeypatch.setattr(store, "dispatch_needed", cancellation_after_snapshot)
    assert await store.dispatch("worker") == []
    assert (await store.get(job["id"]))["status"] == "cancelled"


async def test_dispatch_read_preflight_detects_expired_leases_without_queued_jobs(store):
    job = await store.admit(request())
    attempt = (await store.claim("lost-worker"))["attempt"]
    assert await store.dispatch_needed() is False
    async with store.transaction() as conn:
        await conn.execute(
            update(attempts).where(attempts.c.id == attempt["id"]).values(lease_until=0)
        )
    assert await store.dispatch_needed() is True
    assert await store.dispatch("worker", capacity=0) == []
    assert (await store.get(job["id"]))["status"] == "uncertain"
    with pytest.raises(Fenced):
        await store.append(attempt, "text.delta", {"text": "stale"})


async def test_claim_statement_failure_rolls_back_attempt_job_and_conversation_lock(
    store, monkeypatch
):
    from sqlalchemy import select

    from tsukai.tables import jobs, locks

    job = await store.admit(request(profile="chat", conversation_id="atomic-claim"))
    original = store._event

    async def fail_started(conn, job_id, kind, *args, **kwargs):
        if kind == "attempt.started":
            raise RuntimeError("injected after claim writes")
        return await original(conn, job_id, kind, *args, **kwargs)

    monkeypatch.setattr(store, "_event", fail_started)
    with pytest.raises(RuntimeError, match="injected"):
        await store.claim("worker")
    async with store.read_connection() as conn:
        state = (await conn.execute(select(jobs).where(jobs.c.id == job["id"]))).mappings().one()
        held = (
            (await conn.execute(select(locks).where(locks.c.job_id == job["id"]))).mappings().one()
        )
        assert (
            await conn.execute(select(attempts).where(attempts.c.job_id == job["id"]))
        ).first() is None
    assert state["status"] == "queued" and state["attempt_count"] == 0
    assert held["attempt_id"] is None and held["fence"] is None
    monkeypatch.setattr(store, "_event", original)
    claimed = await store.claim("worker")
    assert claimed["attempt"]["number"] == 1
    assert claimed["repair_diagnostic"] is None


async def test_pg_admission_snapshot_and_claim_use_bounded_roundtrips(store):
    from sqlalchemy import event, select

    from tsukai.tables import jobs, locks

    if store.engine.dialect.name != "postgresql":
        pytest.skip("production PostgreSQL snapshot and atomic DML")
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(store.engine.sync_engine, "before_cursor_execute", record)
    try:
        req = request(profile="chat", conversation_id="雪-unicode", prompt='quoted "evidence"')
        job = await store.admit(req)
        admission = list(statements)
        statements.clear()
        assert (await store.admit(req)) == job
        statements.clear()
        claim = await store.claim("worker")
        claiming = list(statements)
    finally:
        event.remove(store.engine.sync_engine, "before_cursor_execute", record)
    # One snapshot carries live tombstones, idempotency, capacity, lock and session.
    assert sum("row_to_json" in sql for sql in admission) == 1
    assert sum("json_agg" in sql for sql in claiming) == 1
    assert sum("created_attempt AS" in sql for sql in claiming) == 1
    assert not any("tsukai_attempts.diagnostic" in sql for sql in claiming)
    assert claim["attempt"]["number"] == 1
    async with store.read_connection() as conn:
        state = (await conn.execute(select(jobs).where(jobs.c.id == job["id"]))).mappings().one()
        held = (
            (await conn.execute(select(locks).where(locks.c.job_id == job["id"]))).mappings().one()
        )
    assert state["status"] == "running" and state["attempt_count"] == 1
    assert held["attempt_id"] == claim["attempt"]["id"]
    assert held["fence"] == claim["attempt"]["fence"]
    assert held["lease_until"] == claim["attempt"]["lease_until"]
