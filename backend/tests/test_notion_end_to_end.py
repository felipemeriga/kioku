import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from services.notion_sync.client import NotionPage
from services.notion_sync.sync_engine import fast_poll


class TestEndToEnd(unittest.TestCase):
    def test_fast_poll_ingests_one_changed_page(self):
        supabase = MagicMock()
        # No existing chunks; delete/select/update/insert all return sensible empties
        table = supabase.table.return_value
        delete_chain = table.delete.return_value.eq.return_value.eq.return_value.eq.return_value
        delete_chain.execute.return_value.data = []
        table.insert.return_value.execute.return_value.data = [{"id": "doc-1"}]
        select_chain = table.select.return_value.eq.return_value.eq.return_value
        select_chain.execute.return_value.data = []
        table.update.return_value.eq.return_value.execute.return_value.data = [{}]

        client = MagicMock()
        now = datetime.now(timezone.utc)
        client.iter_pages_edited_since.return_value = iter(
            [
                NotionPage(
                    page_id="p1",
                    title="Overview",
                    parent_page_id="cosm",
                    last_edited_time=now,
                ),
            ]
        )
        client.get_page.side_effect = lambda pid: {
            "p1": NotionPage(
                page_id="p1",
                title="Overview",
                parent_page_id="cosm",
                last_edited_time=now,
            ),
            "cosm": NotionPage(
                page_id="cosm",
                title="Cosm",
                parent_page_id=None,
                last_edited_time=now,
            ),
        }[pid]
        client.iter_child_blocks.return_value = iter(
            [
                {
                    "type": "heading_1",
                    "has_children": False,
                    "heading_1": {"rich_text": [{"plain_text": "Hi"}]},
                }
            ]
        )

        cfg = {
            "id": "cfg",
            "user_id": "u1",
            "root_folder_id": "root",
            "notion_page_id": "cosm",
            "integration_token_encrypted": "unused-here",
            "fast_poll_interval_min": 5,
            "last_fast_sync_at": None,
        }

        with (
            patch(
                "services.notion_sync.ingest.ensure_notion_folder_path",
                return_value=("leaf", ""),
            ),
            patch("services.notion_sync.ingest.chunk_text", return_value=["Hi"]),
            patch("services.notion_sync.ingest.embed_document", return_value=[0.0] * 1024),
            patch("services.notion_sync.ingest.extract_metadata", return_value={}),
        ):
            result = fast_poll(supabase, client, cfg)

        self.assertEqual(result["processed"], 1)
        self.assertEqual(result["errors"], 0)
        inserted_rows = [c.args[0] for c in supabase.table.return_value.insert.call_args_list]
        matching = [r for r in inserted_rows if r.get("notion_page_id") == "p1"]
        self.assertTrue(matching)
        self.assertEqual(matching[0]["source_type"], "notion")
