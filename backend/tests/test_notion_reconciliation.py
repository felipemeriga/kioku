import unittest
from datetime import datetime, timedelta, timezone

from services.notion_sync.client import NotionPage
from services.notion_sync.reconciliation import (
    NotionPageSnapshot,
    diff_pages,
    pending_pages,
)


def _snap(pid, edited):
    return NotionPageSnapshot(page_id=pid, last_edited_time=edited)


def _page(pid, title, edited):
    return NotionPage(page_id=pid, title=title, last_edited_time=edited, parent_page_id="root")


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


class TestPendingPages(unittest.TestCase):
    """pending_pages must mirror diff_pages.to_ingest exactly — it's the UI's
    preview of what a Reconcile will ingest — but with titles and reasons."""

    def test_missing_and_outdated_with_reasons(self):
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        new = datetime.now(timezone.utc)
        pending = pending_pages(
            notion_pages=[
                _page("unchanged", "Fine", old),
                _page("edited", "Stale", new),
                _page("new", "Missing", new),
            ],
            db_page_map={"unchanged": old, "edited": old},
        )
        by_id = {p.page_id: p for p in pending}
        self.assertEqual(set(by_id), {"edited", "new"})
        self.assertEqual(by_id["new"].reason, "missing")
        self.assertEqual(by_id["new"].title, "Missing")
        self.assertEqual(by_id["edited"].reason, "outdated")

    def test_everything_synced_returns_empty(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(
            pending_pages(notion_pages=[_page("p1", "T", now)], db_page_map={"p1": now}),
            [],
        )

    def test_matches_diff_pages_to_ingest(self):
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        new = datetime.now(timezone.utc)
        pages = [_page("a", "A", new), _page("b", "B", old), _page("c", "C", new)]
        db_map = {"b": old, "c": old}
        diff = diff_pages(
            notion_pages=[_snap(p.page_id, p.last_edited_time) for p in pages],
            db_page_map=db_map,
        )
        pending = pending_pages(notion_pages=pages, db_page_map=db_map)
        self.assertEqual(sorted(p.page_id for p in pending), sorted(diff.to_ingest))
