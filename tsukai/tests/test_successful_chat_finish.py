"""Successful-chat batching keeps fenced terminal state and transcript bookkeeping atomic."""

import time
import uuid

import pytest
from sqlalchemy import delete, event, insert, select, update
from sqlalchemy.exc import IntegrityError

from tsukai.protocol import JobRequest
from tsukai.store import Fenced
from tsukai.tables import attempts, events, jobs, locks, sessions


def request(**kwargs):
    return JobRequest(
        idempotency_key=str(uuid.uuid4()),
        owner_id="owner",
        caller="backend",
        operation="test",
        prompt="fixture evidence",
        **kwargs,
    )


async def running(store, **kwargs):
    job = await store.admit(request(profile="chat", conversation_id="conversation", **kwargs))
    return job, (await store.claim("worker"))["attempt"]


async def snapshot(store, job_id):
    async with store.read_connection() as conn:
        return {
            table.name: [dict(row) for row in (await conn.execute(select(table))).mappings()]
            for table in (jobs, attempts, sessions, locks, events)
        }


def record_statements(store):
    statements = []

    def record(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(store.engine.sync_engine, "before_cursor_execute", record)
    return statements, record


async def test_successful_chat_one_pg_statement_preserves_result_usage_and_replay(store):
    job, attempt = await running(store)
    attempt.update(first_event_at=time.time(), first_text_at=time.time())
    usage = {"native_total_cost_usd": 1.25, "native_counters": {"output_tokens": 17}}
    result = {"text": "quoted ' $1\n café 🚀", "usage": usage}
    diagnostic = {"reason": "fixture", "nested": [1, None]}
    statements, record = record_statements(store)
    try:
        await store.finish(attempt, "completed", result=result, diagnostic=diagnostic)
    finally:
        event.remove(store.engine.sync_engine, "before_cursor_execute", record)
    state = await snapshot(store, job["id"])
    current = state[jobs.name][0]
    finished = state[attempts.name][0]
    session = state[sessions.name][0]
    expected = {**result, "attempt_id": attempt["id"]}
    assert current["status"] == finished["status"] == "completed"
    assert current["result"] == expected and current["error"] is None
    assert finished["usage"] == usage and finished["diagnostic"] == diagnostic
    assert finished["first_event_at"] == attempt["first_event_at"]
    assert finished["first_text_at"] == attempt["first_text_at"]
    assert finished["finished_at"] is not None and finished["error"] is None
    assert session["state"] == "ready" and session["last_cost"] == 1.25
    assert session["last_counters"] == usage["native_counters"]
    assert not state[locks.name]
    replay = await store.replay(job["id"])
    assert replay[-1]["type"] == "job.completed"
    assert replay[-1]["data"] == {"result": expected, "error": None}
    assert replay[-1]["attempt_id"] == attempt["id"]
    assert [r["seq"] for r in replay] == list(range(1, current["next_seq"]))
    if store.engine.dialect.name == "postgresql":
        dml = [
            s
            for s in statements
            if s.lstrip().upper().startswith(("WITH", "UPDATE", "INSERT", "DELETE"))
        ]
        assert len(dml) == 1
        assert dml[0].count("UPDATE tsukai_jobs") == 1
        assert all(
            name in dml[0]
            for name in ("finished_attempt", "refreshed_session", "completed_job", "released_locks")
        )
        assert "INSERT INTO tsukai_events" in dml[0]
        assert any("pg_advisory_xact_lock" in s for s in statements)
        assert any("tsukai_attempts JOIN tsukai_jobs" in s for s in statements)


async def test_terminal_event_failure_rolls_back_attempt_session_usage_job_and_locks(store):
    job, attempt = await running(store)
    # An actual SQL uniqueness failure at the final event insert must undo every
    # preceding write, including session counters and the released chat lock.
    current = await store.get(job["id"])
    async with store.transaction() as conn:
        await conn.execute(
            insert(events).values(
                job_id=job["id"],
                seq=current["next_seq"],
                attempt_id=None,
                type="fixture.collision",
                data={},
                created_at=time.time(),
            )
        )
    before = await snapshot(store, job["id"])
    attempt.update(first_event_at=time.time(), first_text_at=time.time())
    with pytest.raises(IntegrityError):
        await store.finish(
            attempt,
            "completed",
            result={
                "text": "must rollback",
                "usage": {"native_total_cost_usd": 3, "native_counters": {"output_tokens": 99}},
            },
            diagnostic={"new": True},
        )
    assert await snapshot(store, job["id"]) == before
    async with store.transaction() as conn:
        await conn.execute(
            delete(events).where(events.c.job_id == job["id"], events.c.seq == current["next_seq"])
        )
    await store.finish(attempt, "completed", result={"text": "recovered", "usage": {}})
    assert (await store.replay(job["id"]))[-1]["data"]["result"]["text"] == "recovered"


@pytest.mark.parametrize("reason", ["fence", "expired", "finished", "foreign_job"])
async def test_fenced_finish_changes_no_terminal_bookkeeping(store, reason):
    job, attempt = await running(store)
    if reason == "fence":
        attempt = {**attempt, "fence": "foreign"}
    elif reason == "foreign_job":
        attempt = {**attempt, "job_id": str(uuid.uuid4())}
    else:
        async with store.transaction() as conn:
            await conn.execute(
                update(attempts)
                .where(attempts.c.id == attempt["id"])
                .values(
                    **(
                        {"lease_until": time.time() - 1}
                        if reason == "expired"
                        else {"status": "completed"}
                    )
                )
            )
    before = await snapshot(store, job["id"])
    with pytest.raises(Fenced):
        await store.finish(attempt, "completed", result={"text": "rejected", "usage": {}})
    assert await snapshot(store, job["id"]) == before


async def test_cancel_request_still_overrides_success_and_rebuilds_session(store):
    job, attempt = await running(store)
    await store.cancel(job["id"])
    await store.finish(attempt, "completed", result={"text": "not published", "usage": {}})
    current = await store.get(job["id"])
    assert current["status"] == "cancelled" and current["result"] is None
    assert current["error"] == {"code": "cancelled", "usage_complete": False}
    state = await snapshot(store, job["id"])
    assert state[sessions.name][0]["state"] == "needs_rebuild"
    assert state[attempts.name][0]["usage"] is None
    assert not state[locks.name]
    assert (await store.replay(job["id"]))[-1]["type"] == "job.cancelled"


async def test_successful_finish_keeps_resume_mapping_and_releases_conversation_lock(store):
    _, first = await running(store)
    await store.finish(first, "completed", result={"text": "first", "usage": {}})
    second = await store.admit(request(profile="chat", conversation_id="conversation"))
    resumed = (await store.claim("next-worker"))["attempt"]
    assert resumed["job_id"] == second["id"] and resumed["resume"]
    assert resumed["native_session_id"] == first["native_session_id"]
    await store.finish(resumed, "completed", result={"text": "second", "usage": {}})


async def test_missing_session_row_does_not_suppress_successful_terminal_event(store):
    job, attempt = await running(store)
    async with store.transaction() as conn:
        await conn.execute(
            delete(sessions).where(
                sessions.c.owner_id == "owner", sessions.c.conversation_id == "conversation"
            )
        )
    await store.finish(attempt, "completed", result={"text": "still durable", "usage": {}})
    assert (await store.get(job["id"]))["status"] == "completed"
    assert (await store.replay(job["id"]))[-1]["type"] == "job.completed"
    state = await snapshot(store, job["id"])
    assert not state[sessions.name] and not state[locks.name]
