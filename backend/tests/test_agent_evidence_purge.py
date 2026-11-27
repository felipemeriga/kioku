import asyncio
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.agent_evidence_purge import purge_evidence_outbox


def outbox(paths):
    sb = MagicMock()
    table = sb.table.return_value
    query = table.select.return_value.lte.return_value.order.return_value.limit.return_value
    query.execute.return_value = SimpleNamespace(
        data=[{"id": "receipt", "storage_paths": paths, "attempts": 2}]
    )
    return sb, table, sb.storage.from_.return_value


def test_purge_keeps_receipt_until_every_storage_chunk_succeeds():
    paths = [f"private/object-{index}" for index in range(1001)]
    sb, table, storage = outbox(paths)
    storage.remove.side_effect = [None, RuntimeError("storage unavailable")]
    purge_evidence_outbox(sb)
    table.delete.assert_not_called()
    table.update.assert_called_once_with({"attempts": 3})
    assert [len(call.args[0]) for call in storage.remove.call_args_list] == [1000, 1]

    storage.remove.side_effect = None
    purge_evidence_outbox(sb)
    table.delete.return_value.eq.assert_called_once_with("id", "receipt")
    assert storage.remove.call_args_list[-2].args[0] == paths[:1000]
    assert storage.remove.call_args_list[-1].args[0] == paths[1000:]


def test_empty_receipt_finishes_without_storage_call():
    sb, table, storage = outbox([])
    purge_evidence_outbox(sb)
    storage.remove.assert_not_called()
    table.delete.return_value.eq.assert_called_once_with("id", "receipt")


def test_disabled_capture_still_processes_erasure_receipts():
    from services.agent_evidence_jobs import (
        agent_evidence_maintenance,
        initialize_evidence_maintenance,
    )

    with (
        patch("services.agent_evidence_jobs.enabled", return_value=False),
        patch("services.agent_evidence_jobs.get_supabase_thread_safe", return_value="db"),
        patch("services.agent_evidence_jobs.purge_evidence_outbox") as purge,
        patch("services.agent_evidence_jobs.purge_tombstoned_sessions") as tombstones,
        patch("services.agent_evidence_jobs.reap_evidence") as capture,
    ):
        ctx = {}
        initialize_evidence_maintenance(ctx)
        asyncio.run(agent_evidence_maintenance({**ctx}))
    purge.assert_called_once_with("db")
    tombstones.assert_called_once_with("db")
    capture.assert_not_called()


def test_tombstone_purge_respects_storage_bulk_limit():
    from services.agent_evidence_jobs import purge_session

    sb = MagicMock()
    records = [{"object_id": str(index), "storage_path": str(index)} for index in range(1000)]
    with patch("services.agent_evidence_jobs.EvidenceStore") as store:
        query = store.return_value._query.return_value.eq.return_value.limit.return_value
        query.execute.return_value = SimpleNamespace(data=records)
        store.return_value.prefix.return_value = "private/session"
        purge_session(sb, {"id": "session", "user_id": "owner", "folder_id": "folder"})
    calls = sb.storage.from_.return_value.remove.call_args_list
    assert [len(call.args[0]) for call in calls] == [1000, 1]


def test_evidence_cron_skips_overlapping_sweeps_until_scan_releases_gate():
    from services.agent_evidence_jobs import (
        agent_evidence_maintenance,
        initialize_evidence_maintenance,
    )

    entered = Event()
    release = Event()

    def reap(_sb, cursor):
        if cursor is None:
            entered.set()
            assert release.wait(2)
            return "next-page"
        assert cursor == "next-page"
        return None

    async def check():
        from contextlib import suppress

        worker_ctx = {}
        initialize_evidence_maintenance(worker_ctx)
        state = worker_ctx["evidence_maintenance_state"]
        first = asyncio.create_task(agent_evidence_maintenance({**worker_ctx, "job_id": "first"}))
        assert await asyncio.to_thread(entered.wait, 2)
        first.cancel()
        with suppress(asyncio.CancelledError):
            await first
        await agent_evidence_maintenance({**worker_ctx, "job_id": "overlapping"})
        assert state["cursor"] is None
        release.set()
        # Synchronize with the worker-owned lock before sending the next tick.
        lock = state["lock"]
        assert await asyncio.to_thread(lock.acquire, True, 2)
        lock.release()
        assert state["cursor"] == "next-page"
        await agent_evidence_maintenance({**worker_ctx, "job_id": "next"})
        assert state["cursor"] is None

    with (
        patch("services.agent_evidence_jobs.enabled", return_value=True),
        patch("services.agent_evidence_jobs.get_supabase_thread_safe", return_value="db"),
        patch("services.agent_evidence_jobs.purge_evidence_outbox"),
        patch("services.agent_evidence_jobs.purge_tombstoned_sessions"),
        patch("services.agent_evidence_jobs.reap_evidence", side_effect=reap) as capture,
    ):
        asyncio.run(check())
    assert [call.args for call in capture.call_args_list] == [("db", None), ("db", "next-page")]


def test_failed_sweep_releases_shared_gate_without_advancing_cursor():
    from services.agent_evidence_jobs import (
        agent_evidence_maintenance,
        initialize_evidence_maintenance,
    )

    async def check():
        worker_ctx = {}
        initialize_evidence_maintenance(worker_ctx)
        with pytest.raises(RuntimeError, match="database unavailable"):
            await agent_evidence_maintenance({**worker_ctx, "job_id": "failed"})
        assert worker_ctx["evidence_maintenance_state"]["cursor"] is None
        await agent_evidence_maintenance({**worker_ctx, "job_id": "retry"})
        assert worker_ctx["evidence_maintenance_state"]["cursor"] == "next-page"

    with (
        patch("services.agent_evidence_jobs.enabled", return_value=True),
        patch("services.agent_evidence_jobs.get_supabase_thread_safe", return_value="db"),
        patch("services.agent_evidence_jobs.purge_evidence_outbox"),
        patch("services.agent_evidence_jobs.purge_tombstoned_sessions"),
        patch(
            "services.agent_evidence_jobs.reap_evidence",
            side_effect=[RuntimeError("database unavailable"), "next-page"],
        ),
    ):
        asyncio.run(check())


def test_actual_arq_jobs_share_scan_state_across_distinct_contexts():
    import fakeredis.aioredis
    from arq import func
    from arq.connections import ArqRedis
    from arq.worker import Worker

    from services.agent_evidence_jobs import agent_evidence_maintenance
    from services.queue.settings import WorkerSettings

    contexts = []

    async def sweep(ctx):
        contexts.append(ctx)
        await agent_evidence_maintenance(ctx)

    async def check():
        fake = fakeredis.aioredis.FakeRedis()
        pool = ArqRedis(connection_pool=fake.connection_pool)
        worker = Worker(
            [func(sweep, name="sweep")],
            redis_pool=pool,
            on_startup=WorkerSettings.on_startup,
            burst=True,
            max_jobs=1,
            poll_delay=0.01,
            handle_signals=False,
            keep_result=0,
        )
        try:
            for index in range(3):
                await pool.enqueue_job("sweep", _job_id=f"context-{index}")
            await asyncio.wait_for(worker.async_run(), timeout=5)
            assert worker.jobs_complete == 3
            assert worker.jobs_failed == 0
            assert len({id(ctx) for ctx in contexts}) == 3
            state = worker.ctx["evidence_maintenance_state"]
            assert all(ctx["evidence_maintenance_state"] is state for ctx in contexts)
            assert state["cursor"] is None
        finally:
            await worker.close()
            await fake.aclose()

    with (
        patch("arq.worker.log_redis_info", new_callable=AsyncMock),
        patch("services.queue.settings._reap_stale_jobs", new_callable=AsyncMock),
        patch("services.agent_evidence_jobs.enabled", return_value=True),
        patch("services.agent_evidence_jobs.get_supabase_thread_safe", return_value="db"),
        patch("services.agent_evidence_jobs.purge_evidence_outbox"),
        patch("services.agent_evidence_jobs.purge_tombstoned_sessions"),
        patch(
            "services.agent_evidence_jobs.reap_evidence",
            side_effect=["page-two", "page-three", None],
        ) as capture,
    ):
        asyncio.run(check())
    assert [call.args for call in capture.call_args_list] == [
        ("db", None),
        ("db", "page-two"),
        ("db", "page-three"),
    ]
