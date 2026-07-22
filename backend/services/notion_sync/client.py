"""Thin wrapper over notion-client that exposes only what the sync engine needs.

Keeping this small makes it trivial to mock in tests: swap `NotionClient` for a
fake with the same three methods.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterator

from notion_client import Client


@dataclass(frozen=True)
class NotionPage:
    page_id: str
    title: str
    last_edited_time: datetime
    parent_page_id: str | None  # None if top-level (workspace-level parent)


class NotionClient:
    """Minimal Notion API surface used by the sync engine."""

    def __init__(self, token: str):
        self._client = Client(auth=token)

    def get_page(self, page_id: str) -> NotionPage:
        page = self._client.pages.retrieve(page_id=page_id)
        return _page_from_raw(page)

    def iter_child_blocks(self, block_id: str) -> Iterator[dict]:
        """Yield all children of a block (page or block), paginated."""
        cursor: str | None = None
        while True:
            resp = self._client.blocks.children.list(
                block_id=block_id, start_cursor=cursor, page_size=100
            )
            for block in resp.get("results", []):
                yield block
            if not resp.get("has_more"):
                return
            cursor = resp.get("next_cursor")

    def iter_pages_edited_since(self, since: datetime | None) -> Iterator[NotionPage]:
        """Search all pages accessible to the integration, newest edits first.

        Stops iterating once we cross `since`. Caller filters by ancestry.
        """
        cursor: str | None = None
        while True:
            resp = self._client.search(
                query="",
                filter={"value": "page", "property": "object"},
                sort={"direction": "descending", "timestamp": "last_edited_time"},
                start_cursor=cursor,
                page_size=100,
            )
            for raw in resp.get("results", []):
                page = _page_from_raw(raw)
                if since is not None and page.last_edited_time <= since:
                    return
                yield page
            if not resp.get("has_more"):
                return
            cursor = resp.get("next_cursor")


def _page_from_raw(raw: dict) -> NotionPage:
    parent = raw.get("parent", {})
    parent_page_id = parent.get("page_id") if parent.get("type") == "page_id" else None
    title = _extract_title(raw)
    return NotionPage(
        page_id=raw["id"],
        title=title,
        last_edited_time=datetime.fromisoformat(raw["last_edited_time"].replace("Z", "+00:00")),
        parent_page_id=parent_page_id,
    )


def _extract_title(raw: dict) -> str:
    """Notion page titles live under a rich_text property whose key varies."""
    props = raw.get("properties", {})
    for value in props.values():
        if value.get("type") == "title":
            fragments = value.get("title", [])
            return "".join(f.get("plain_text", "") for f in fragments) or "Untitled"
    return "Untitled"
