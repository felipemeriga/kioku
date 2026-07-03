import unittest
from datetime import datetime, timedelta, timezone

from services.notion_sync.reconciliation import (
    NotionPageSnapshot,
    diff_pages,
)


def _snap(pid, edited):
    return NotionPageSnapshot(page_id=pid, last_edited_time=edited)


class TestDiffPages(unittest.TestCase):
    def test_new_page(self):
        now = datetime.now(timezone.utc)
        diff = diff_pages(
            notion_pages=[_snap("p1", now)],
            db_page_map={},
        )
        self.assertEqual(diff.to_ingest, ["p1"])
        self.assertEqual(diff.to_tombstone, [])

    def test_unchanged_page_skipped(self):
        now = datetime.now(timezone.utc)
        diff = diff_pages(
            notion_pages=[_snap("p1", now)],
            db_page_map={"p1": now},
        )
        self.assertEqual(diff.to_ingest, [])
        self.assertEqual(diff.to_tombstone, [])

    def test_changed_page_reingested(self):
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        new = datetime.now(timezone.utc)
        diff = diff_pages(
            notion_pages=[_snap("p1", new)],
            db_page_map={"p1": old},
        )
        self.assertEqual(diff.to_ingest, ["p1"])

    def test_deleted_page_tombstoned(self):
        now = datetime.now(timezone.utc)
        diff = diff_pages(
            notion_pages=[],
            db_page_map={"gone": now},
        )
        self.assertEqual(diff.to_ingest, [])
        self.assertEqual(diff.to_tombstone, ["gone"])

    def test_mixed_case(self):
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        new = datetime.now(timezone.utc)
        diff = diff_pages(
            notion_pages=[
                _snap("unchanged", old),
                _snap("edited", new),
                _snap("new", new),
            ],
            db_page_map={
                "unchanged": old,
                "edited": old,
                "deleted": old,
            },
        )
        self.assertEqual(sorted(diff.to_ingest), ["edited", "new"])
        self.assertEqual(diff.to_tombstone, ["deleted"])
