"""Pure diff helper for full reconciliation.

Compares the set of pages currently in Notion against what we have in the
documents table so we only re-ingest what actually changed and tombstone what
disappeared.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.notion_sync.client import NotionPage


@dataclass(frozen=True)
class NotionPageSnapshot:
    page_id: str
    last_edited_time: datetime


@dataclass(frozen=True)
class ReconciliationDiff:
    to_ingest: list[str]  # page_ids that are new or edited
    to_tombstone: list[str]  # page_ids that disappeared from Notion


def diff_pages(
    notion_pages: list[NotionPageSnapshot],
    db_page_map: dict[str, datetime],
) -> ReconciliationDiff:
    """
    notion_pages: pages currently reachable under the mapped root.
    db_page_map: existing (notion_page_id -> last_edited_time) from documents table.
    """
    reachable = {p.page_id for p in notion_pages}
    to_ingest: list[str] = []

    for p in notion_pages:
        stored = db_page_map.get(p.page_id)
        if stored is None:
            # New page
            to_ingest.append(p.page_id)
            continue
        # Changed page: Notion edit time strictly newer than what we stored
        if p.last_edited_time > stored:
            to_ingest.append(p.page_id)

    to_tombstone = [pid for pid in db_page_map.keys() if pid not in reachable]

    return ReconciliationDiff(to_ingest=to_ingest, to_tombstone=to_tombstone)


@dataclass(frozen=True)
class PendingPage:
    page_id: str
    title: str
    reason: str  # "missing" (not in kioku) | "outdated" (edited since last ingest)


def pending_pages(
    notion_pages: list[NotionPage],
    db_page_map: dict[str, datetime],
) -> list[PendingPage]:
    """The UI-facing preview of a reconcile: which pages it would ingest and
    why. Must stay in lockstep with diff_pages.to_ingest — same inputs, same
    pages — just enriched with titles and reasons."""
    pending: list[PendingPage] = []
    for p in notion_pages:
        stored = db_page_map.get(p.page_id)
        if stored is None:
            pending.append(PendingPage(page_id=p.page_id, title=p.title, reason="missing"))
        elif p.last_edited_time > stored:
            pending.append(PendingPage(page_id=p.page_id, title=p.title, reason="outdated"))
    return pending
