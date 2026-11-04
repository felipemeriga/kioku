from types import SimpleNamespace
from unittest.mock import MagicMock

from services.agent_evidence_purge import purge_evidence_outbox


def outbox(paths):
    sb = MagicMock()
    table = sb.table.return_value
    table.select.return_value.lte.return_value.order.return_value.limit.return_value.execute.return_value = SimpleNamespace(
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
