import asyncio
from threading import Event
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
    from services.agent_evidence_jobs import agent_evidence_maintenance

    with (
        patch("services.agent_evidence_jobs.enabled", return_value=False),
        patch("services.agent_evidence_jobs.get_supabase_thread_safe", return_value="db"),
        patch("services.agent_evidence_jobs.purge_evidence_outbox") as purge,
        patch("services.agent_evidence_jobs.purge_tombstoned_sessions") as tombstones,
        patch("services.agent_evidence_jobs.reap_evidence") as capture,
    ):
        asyncio.run(agent_evidence_maintenance({}))
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
    from services.agent_evidence_jobs import agent_evidence_maintenance

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

        ctx = {}
        first = asyncio.create_task(agent_evidence_maintenance(ctx))
        assert await asyncio.to_thread(entered.wait, 2)
        first.cancel()
        with suppress(asyncio.CancelledError):
            await first
        await agent_evidence_maintenance(ctx)
        assert "evidence_cursor" not in ctx
        release.set()
        # Synchronize with the worker-owned lock before sending the next tick.
        lock = ctx["evidence_maintenance_lock"]
        assert await asyncio.to_thread(lock.acquire, True, 2)
        lock.release()
        assert ctx["evidence_cursor"] == "next-page"
        await agent_evidence_maintenance(ctx)
        assert ctx["evidence_cursor"] is None

    with (
        patch("services.agent_evidence_jobs.enabled", return_value=True),
        patch("services.agent_evidence_jobs.get_supabase_thread_safe", return_value="db"),
        patch("services.agent_evidence_jobs.purge_evidence_outbox"),
        patch("services.agent_evidence_jobs.purge_tombstoned_sessions"),
        patch("services.agent_evidence_jobs.reap_evidence", side_effect=reap) as capture,
    ):
        asyncio.run(check())
    assert [call.args for call in capture.call_args_list] == [("db", None), ("db", "next-page")]
