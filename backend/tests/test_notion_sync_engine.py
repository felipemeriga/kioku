import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from services.notion_sync.client import NotionPage


def _cfg(**kw):
    base = {
        "id": "cfg-1",
        "user_id": "u1",
        "root_folder_id": "root-1",
        "notion_page_id": "cosm",
        "integration_token_encrypted": "encrypted",
        "fast_poll_interval_min": 5,
        "full_reconciliation_interval_hours": 24,
        "last_fast_sync_at": None,
        "last_full_sync_at": None,
    }
    base.update(kw)
    return base


def _page(pid, title, parent, edited):
    return NotionPage(
        page_id=pid,
        title=title,
        parent_page_id=parent,
        last_edited_time=edited,
    )


class TestFastPoll(unittest.TestCase):
    def test_ingests_only_pages_under_mapped_root(self):
        from services.notion_sync.sync_engine import fast_poll

        supabase = MagicMock()
        client = MagicMock()

        now = datetime.now(timezone.utc)
        under_root = _page("p1", "A", parent="cosm", edited=now)
        unrelated = _page("p2", "B", parent="other", edited=now)
        client.iter_pages_edited_since.return_value = iter([under_root, unrelated])
        client.get_page.side_effect = lambda pid: {
            "cosm": _page("cosm", "Cosm", parent=None, edited=now),
            "other": _page("other", "Other", parent=None, edited=now),
        }[pid]

        with patch("services.notion_sync.sync_engine.ingest_notion_page") as ingest:
            fast_poll(supabase, client, _cfg())

        ingested_page_ids = [c.kwargs["page_id"] for c in ingest.call_args_list]
        self.assertEqual(ingested_page_ids, ["p1"])


class TestFullReconciliation(unittest.TestCase):
    def test_tombstones_missing_pages(self):
        from services.notion_sync.sync_engine import full_reconciliation

        client = MagicMock()
        now = datetime.now(timezone.utc)
        client.get_page.return_value = _page("cosm", "Cosm", parent=None, edited=now)
        client.iter_child_blocks.return_value = iter(
            [
                {
                    "type": "child_page",
                    "id": "p1",
                    "child_page": {"title": "A"},
                    "has_children": False,
                },
            ]
        )

        supabase = MagicMock()
        table = supabase.table.return_value
        select_chain = table.select.return_value.eq.return_value.eq.return_value.eq.return_value
        select_chain.execute.return_value.data = [
            {"notion_page_id": "p1"},
            {"notion_page_id": "p_gone"},
        ]

        with patch("services.notion_sync.sync_engine.ingest_notion_page"):
            full_reconciliation(supabase, client, _cfg())

        tombstone_calls = [
            c
            for c in supabase.table.return_value.update.call_args_list
            if c.args and c.args[0].get("status") == "deleted"
        ]
        self.assertTrue(tombstone_calls, "expected an update setting status='deleted'")


class TestSyncLoopSchedules(unittest.TestCase):
    def test_only_returns_configs_whose_intervals_elapsed(self):
        from services.notion_sync.sync_engine import _configs_due_for_fast_poll

        now = datetime.now(timezone.utc)
        due = _cfg(
            id="a",
            last_fast_sync_at=(now - timedelta(minutes=10)).isoformat(),
            fast_poll_interval_min=5,
        )
        not_due = _cfg(
            id="b",
            last_fast_sync_at=(now - timedelta(minutes=1)).isoformat(),
            fast_poll_interval_min=5,
        )
        never = _cfg(id="c", last_fast_sync_at=None, fast_poll_interval_min=5)

        result = _configs_due_for_fast_poll([due, not_due, never], now=now)
        self.assertEqual({c["id"] for c in result}, {"a", "c"})
