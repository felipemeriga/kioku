"""Actual SQL cancellation releases fenced transaction resources without leaking data."""

import asyncio
import os
import time
from contextlib import AsyncExitStack

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import create_async_engine
from test_store import request

from tsukai import store as store_module
from tsukai.store import Store
from tsukai.tables import attempts, events, jobs


@pytest.mark.parametrize("wait", ["local_lock", "advisory_lock", "connection_begin"])
async def test_live_wait_diagnostics_identify_stage_and_preserve_renewal(
    store, monkeypatch, caplog, wait
):
    if store.engine.dialect.name != "postgresql":
        pytest.skip("production PostgreSQL lock and connection stages")
    await store.admit(request())
    attempt = (await store.claim("worker"))["attempt"]
    monkeypatch.setattr(store_module, "TRANSACTION_WARN_SECONDS", 0.02)
    caplog.set_level("WARNING", logger="uvicorn.error")
    other = None
    try:
        async with AsyncExitStack() as stack:
            if wait == "local_lock":
                await stack.enter_async_context(store._local_lock)
            elif wait == "advisory_lock":
                other = Store(store.engine.url.render_as_string(hide_password=False))
                await stack.enter_async_context(other.transaction())
            else:
                for _ in range(4):
                    await stack.enter_async_context(store.read_connection())
            pending = asyncio.create_task(store.heartbeat(attempt))
            await asyncio.sleep(0.06)
            assert any(
                "outcome=waiting" in r.message and f"phase={wait}" in r.message
                for r in caplog.records
            )
        await pending
        assert attempt["lease_until"] > time.time() + 20
        assert any("operation=heartbeat" in r.message for r in caplog.records)
    finally:
        if other:
            await other.engine.dispose()


async def test_cancelling_blocked_actual_pg_insert_rolls_back_all_writes_and_releases_locks(
    store, caplog
):
    if store.engine.dialect.name != "postgresql":
        pytest.skip("actual PostgreSQL query cancellation")
    job = await store.admit(request())
    attempt = (await store.claim("worker"))["attempt"]
    async with store.read_connection() as conn:
        before_job = dict(
            (await conn.execute(select(jobs).where(jobs.c.id == job["id"]))).mappings().one()
        )
        before_attempt = dict(
            (await conn.execute(select(attempts).where(attempts.c.id == attempt["id"])))
            .mappings()
            .one()
        )
    admin = create_async_engine(os.environ["TSUKAI_TEST_ADMIN_DATABASE_URL"])
    async with admin.begin() as conn:
        await conn.exec_driver_sql(
            "CREATE OR REPLACE FUNCTION public.fixture_slow_event() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN PERFORM pg_sleep(10); RETURN NEW; END $$"
        )
        await conn.exec_driver_sql(
            "CREATE TRIGGER fixture_slow_event BEFORE INSERT ON public.tsukai_events "
            "FOR EACH ROW EXECUTE FUNCTION public.fixture_slow_event()"
        )
    entered = asyncio.Event()

    def started(conn, cursor, statement, parameters, context, many):
        if "INSERT INTO tsukai_events" in statement:
            entered.set()

    event.listen(store.engine.sync_engine, "before_cursor_execute", started)
    attempt.update(first_event_at=time.time(), first_text_at=time.time())
    task = asyncio.create_task(
        store.append(attempt, "text.delta", {"text": "private-evidence-never-log"})
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        await asyncio.sleep(0.1)
        caplog.set_level("WARNING", logger="uvicorn.error")
        began = time.monotonic()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert time.monotonic() - began < 2
        assert not store._local_lock.locked()
        async with store.read_connection() as conn:
            assert (
                dict(
                    (await conn.execute(select(jobs).where(jobs.c.id == job["id"])))
                    .mappings()
                    .one()
                )
                == before_job
            )
            assert (
                dict(
                    (await conn.execute(select(attempts).where(attempts.c.id == attempt["id"])))
                    .mappings()
                    .one()
                )
                == before_attempt
            )
            assert (
                len((await conn.execute(select(events).where(events.c.job_id == job["id"]))).all())
                == 2
            )
        assert "private-evidence-never-log" not in caplog.text
        assert "error_type=CancelledError" in caplog.text
    finally:
        event.remove(store.engine.sync_engine, "before_cursor_execute", started)
        if not task.done():
            task.cancel()
        async with admin.begin() as conn:
            await conn.exec_driver_sql("DROP TRIGGER fixture_slow_event ON public.tsukai_events")
            await conn.exec_driver_sql("DROP FUNCTION public.fixture_slow_event()")
        await admin.dispose()
    # Both the original connection pool and another replica can take the lock again.
    other = Store(store.engine.url.render_as_string(hide_password=False))
    try:
        await asyncio.wait_for(other.heartbeat(attempt), 2)
        await store.append(attempt, "text.delta", {"text": "recovered"})
    finally:
        await other.engine.dispose()


async def test_database_error_logs_only_class_and_sqlstate_never_sql_or_content(store, caplog):
    from sqlalchemy.exc import IntegrityError

    if store.engine.dialect.name != "postgresql":
        pytest.skip("actual PostgreSQL SQLSTATE")
    job = await store.admit(request())
    attempt = (await store.claim("worker"))["attempt"]
    caplog.set_level("WARNING", logger="uvicorn.error")
    with pytest.raises(IntegrityError):
        await store.tool_events(
            job["id"], attempt["id"], [(None, {"text": "secret-not-in-diagnostic"})]
        )
    assert "error_type=IntegrityError sqlstate=23502" in caplog.text
    assert "operation=tool_events" in caplog.text and "phase=rollback" in caplog.text
    assert "secret-not-in-diagnostic" not in caplog.text
    assert "INSERT INTO" not in caplog.text
