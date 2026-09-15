import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from services.notion_sync.client import NotionPage


def _page(pid, title, edited, parent="cosm"):
    return NotionPage(page_id=pid, title=title, last_edited_time=edited, parent_page_id=parent)


class TestComputePending(unittest.TestCase):
    def test_reports_missing_and_outdated_pages(self):
        from routes.notion import _compute_pending

        old = datetime.now(timezone.utc) - timedelta(hours=2)
        new = datetime.now(timezone.utc)

        notion_mock = MagicMock()
        notion_mock.iter_pages_edited_since.return_value = iter(
            [
                _page("synced", "Fine", old),
                _page("stale", "Edited since ingest", new),
                _page("absent", "Never ingested", new),
                _page("outside", "Other tree", new, parent="elsewhere"),
            ]
        )

        cfg = {
            "id": "cfg-1",
            "user_id": "u1",
            "root_folder_id": "root-1",
            "notion_page_id": "cosm",
            "integration_token_encrypted": "ENC",
        }

        def _under_root(notion, page, root):
            return page.parent_page_id == root

        with (
            patch("routes.notion.NotionClient", return_value=notion_mock),
            patch("routes.notion.decrypt_secret", return_value="tok"),
            patch("routes.notion.get_supabase", return_value=MagicMock()),
            patch("services.queue.tasks._is_under_root", side_effect=_under_root),
            patch(
                "services.queue.tasks._load_db_page_edit_map",
                return_value={"synced": old, "stale": old},
            ),
        ):
            result = _compute_pending(cfg)

        self.assertEqual(result.total_in_notion, 3)  # "outside" excluded
        self.assertEqual(result.total_synced, 1)
        by_id = {p.page_id: p for p in result.pending}
        self.assertEqual(set(by_id), {"stale", "absent"})
        self.assertEqual(by_id["absent"].reason, "missing")
        self.assertEqual(by_id["stale"].reason, "outdated")
