"""Append batching retains the existing fenced transaction and replay contract."""

import asyncio
import time
import uuid

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.exc import IntegrityError

from tsukai.protocol import JobRequest
from tsukai.store import Fenced, Store
from tsukai.tables import attempts


def request(**kwargs):
    return JobRequest(
        idempotency_key=str(uuid.uuid4()),
        owner_id="owner",
        caller="backend",
        operation="test",
        prompt="fixture evidence",
        **kwargs,
    )


async def running(store):
    job = await store.admit(request())
    claim = await store.claim("worker")
    return job, claim["attempt"]


async def test_append_batches_pg_bookkeeping_and_preserves_typed_payload(store):
    job, attempt = await running(store)
    attempt.update(first_event_at=time.time(), first_text_at=time.time())
    payload = {"text": "quoted ' $1\n café 🚀", "nested": {"null": None}}
    statements = []

    def record(_conn, _cursor, statement, _parameters, _context, _many):
        statements.append(statement)

    event.listen(store.engine.sync_engine, "before_cursor_execute", record)
    try:
        seq = await store.append(attempt, "text.delta", payload)
    finally:
        event.remove(store.engine.sync_engine, "before_cursor_execute", record)
    replay = await store.replay(job["id"])
    assert replay[-1]["seq"] == seq
    assert replay[-1]["data"] == payload
    assert replay[-1]["attempt_id"] == attempt["id"]
    assert [row["seq"] for row in replay] == list(range(1, len(replay) + 1))
    async with store.read_connection() as conn:
        timing = (
            (await conn.execute(select(attempts).where(attempts.c.id == attempt["id"])))
            .mappings()
            .one()
        )
    assert timing["first_event_at"] == attempt["first_event_at"]
    assert timing["first_text_at"] == attempt["first_text_at"]
    if store.engine.dialect.name == "postgresql":
        dml = [s for s in statements if s.lstrip().upper().startswith(("WITH", "UPDATE", "INSERT"))]
        assert len(dml) == 1
        assert "event_timing" in dml[0] and "event_sequence" in dml[0]
        assert "INSERT INTO tsukai_events" in dml[0]
        assert any("pg_advisory_xact_lock" in s for s in statements)
        assert any("tsukai_attempts JOIN tsukai_jobs" in s for s in statements)


async def test_insert_failure_rolls_back_timing_and_sequence_reservation(store):
    job, attempt = await running(store)
    before = await store.get(job["id"])
    replay = await store.replay(job["id"])
    attempt.update(first_event_at=time.time(), first_text_at=time.time())
    with pytest.raises(IntegrityError):
        await store.append(attempt, None, {"text": "must not be visible"})
    after = await store.get(job["id"])
    assert after["next_seq"] == before["next_seq"]
    assert after["updated_at"] == before["updated_at"]
    assert await store.replay(job["id"]) == replay
    async with store.read_connection() as conn:
        timing = (
            (await conn.execute(select(attempts).where(attempts.c.id == attempt["id"])))
            .mappings()
            .one()
        )
    assert timing["first_event_at"] is None and timing["first_text_at"] is None


@pytest.mark.parametrize("reason", ["fence", "expired", "finished", "job"])
async def test_fenced_append_has_no_partial_bookkeeping(store, reason):
    job, attempt = await running(store)
    before = await store.replay(job["id"])
    if reason == "fence":
        attempt = {**attempt, "fence": "foreign"}
    elif reason == "job":
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
    with pytest.raises(Fenced):
        await store.append(attempt, "text.delta", {"text": "rejected"})
    assert await store.replay(job["id"]) == before


async def test_independent_publishers_preserve_contiguous_sequences(store):
    job, attempt = await running(store)
    other = Store(store.engine.url.render_as_string(hide_password=False))
    try:
        seqs = await asyncio.gather(
            *[
                publisher.append(attempt, "text.delta", {"text": str(index)})
                for index, publisher in enumerate([store, other, store, other])
            ]
        )
    finally:
        await other.engine.dispose()
    assert len(set(seqs)) == 4
    replay = await store.replay(job["id"])
    assert [row["seq"] for row in replay] == list(range(1, len(replay) + 1))
    assert {row["data"]["text"] for row in replay[-4:]} == {"0", "1", "2", "3"}


async def test_metadata_parent_cancellation_still_fences_append(store):
    parent = await store.admit(request(profile="chat", conversation_id="parent"))
    await store.claim("parent-worker")
    child = await store.admit(
        JobRequest(
            idempotency_key=str(uuid.uuid4()),
            owner_id="owner",
            caller="backend",
            operation="text_to_sql",
            prompt="fixture metadata",
            profile="metadata_child",
            ai_depth=1,
            parent_job_id=parent["id"],
            root_job_id=parent["id"],
        )
    )
    attempt = (await store.claim("child-worker"))["attempt"]
    before = await store.replay(child["id"])
    await store.cancel(parent["id"])
    with pytest.raises(Fenced, match="metadata_parent_inactive"):
        await store.append(attempt, "text.delta", {"text": "must remain private"})
    assert await store.replay(child["id"]) == before
