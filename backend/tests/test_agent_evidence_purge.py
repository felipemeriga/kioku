import asyncio
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
