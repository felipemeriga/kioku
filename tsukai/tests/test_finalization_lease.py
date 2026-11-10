"""Finalization saves a renewal only when committed fencing authority permits it."""

import time
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event, select, update

from tsukai.config import Settings
from tsukai.protocol import JobRequest
from tsukai.scheduler import Scheduler
from tsukai.store import Fenced
from tsukai.tables import attempts, locks


async def claim(store):
    await store.admit(
        JobRequest(
            idempotency_key=str(uuid.uuid4()),
            owner_id="owner",
            caller="backend",
            operation="test",
            prompt="fixture",
            profile="chat",
            conversation_id=str(uuid.uuid4()),
        )
    )
    return await store.claim("worker")


async def test_heartbeat_memory_uses_the_exact_committed_attempt_and_lock_lease(store):
    attempt = (await claim(store))["attempt"]
    await store.heartbeat(attempt)
    async with store.engine.connect() as conn:
        persisted = (
            await conn.execute(select(attempts.c.lease_until).where(attempts.c.id == attempt["id"]))
        ).scalar_one()
        locked = (
            await conn.execute(
                select(locks.c.lease_until).where(locks.c.attempt_id == attempt["id"])
            )
        ).scalar_one()
    assert attempt["lease_until"] == persisted == locked


async def test_failed_postgres_heartbeat_commit_cannot_advance_worker_authority(store):
    if store.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL commit-failure acceptance")
    attempt = (await claim(store))["attempt"]
    before = attempt["lease_until"]

    def fail_commit(conn):
        raise RuntimeError("injected commit failure")

    event.listen(store.engine.sync_engine, "commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="commit failure"):
            await store.heartbeat(attempt)
    finally:
        event.remove(store.engine.sync_engine, "commit", fail_commit)
    assert attempt["lease_until"] == before
    async with store.engine.connect() as conn:
        persisted = (
            await conn.execute(select(attempts.c.lease_until).where(attempts.c.id == attempt["id"]))
        ).scalar_one()
    assert persisted == before


@pytest.mark.parametrize("remaining,renewed", [(25, False), (5, True)])
async def test_finalization_renews_only_when_the_exact_lease_is_near_expiry(
    store, monkeypatch, remaining, renewed
):
    value = await claim(store)
    attempt = value["attempt"]
    attempt["lease_until"] = time.time() + remaining
    async with store.transaction() as conn:
        await conn.execute(
            update(attempts)
            .where(attempts.c.id == attempt["id"])
            .values(lease_until=attempt["lease_until"])
        )
    heartbeat = AsyncMock(wraps=store.heartbeat)
    monkeypatch.setattr(store, "heartbeat", heartbeat)
    scheduler = Scheduler(store, Settings(auth_probe=False), AsyncMock())
    await scheduler.finalize_attempt(attempt, "completed", result={"text": "answer", "usage": {}})
    assert heartbeat.await_count == int(renewed)
    job = await store.get(value["job"]["id"])
    assert job["status"] == "completed"
    assert job["result"]["usage"]["runtime_timings"]["finalize_heartbeat_renewed"] is renewed


async def test_skipping_fresh_heartbeat_cannot_bypass_a_lost_persisted_lease(store):
    value = await claim(store)
    attempt = value["attempt"]
    async with store.transaction() as conn:
        await conn.execute(
            update(attempts).where(attempts.c.id == attempt["id"]).values(lease_until=0)
        )
    assert attempt["lease_until"] - time.time() > 20
    scheduler = Scheduler(store, Settings(auth_probe=False), AsyncMock())
    with pytest.raises(Fenced):
        await scheduler.finalize_attempt(
            attempt, "completed", result={"text": "must not publish", "usage": {}}
        )
    job = await store.get(value["job"]["id"])
    assert job["status"] == "running" and job["result"] is None


async def test_finish_commit_log_follows_durable_return_without_persisted_usage_mutation(
    store, monkeypatch, caplog
):
    value = await claim(store)
    attempt = value["attempt"]
    original = store.finish

    async def finish(*args, **kwargs):
        await original(*args, **kwargs)
        assert not any("durable_finish_committed" in record.message for record in caplog.records)

    monkeypatch.setattr(store, "finish", finish)
    scheduler = Scheduler(store, Settings(auth_probe=False), AsyncMock())
    caplog.set_level("INFO", logger="uvicorn.error")
    await scheduler.finalize_attempt(
        attempt, "completed", result={"text": "private answer marker", "usage": {}}
    )
    records = [record for record in caplog.records if "durable_finish_committed" in record.message]
    assert len(records) == 1
    assert records[0].name == "uvicorn.error" and records[0].levelname == "INFO"
    message = records[0].message
    assert f"job_id={attempt['job_id']}" in message
    assert f"attempt_id={attempt['id']}" in message
    assert float(message.rsplit("elapsed_seconds=", 1)[1]) >= 0
    assert "private answer marker" not in message
    job = await store.get(value["job"]["id"])
    assert "durable_finish_seconds" not in job["result"]["usage"]["runtime_timings"]


async def test_failed_finish_commit_does_not_log_committed(store, caplog):
    if store.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL commit-failure acceptance")
    value = await claim(store)
    scheduler = Scheduler(store, Settings(auth_probe=False), AsyncMock())
    caplog.set_level("INFO", logger="uvicorn.error")

    def fail_commit(conn):
        raise RuntimeError("injected finish commit failure")

    event.listen(store.engine.sync_engine, "commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="finish commit failure"):
            await scheduler.finalize_attempt(
                value["attempt"], "completed", result={"text": "not committed", "usage": {}}
            )
    finally:
        event.remove(store.engine.sync_engine, "commit", fail_commit)
    assert not any("durable_finish_committed" in record.message for record in caplog.records)
    job = await store.get(value["job"]["id"])
    assert job["status"] == "running" and job["result"] is None
