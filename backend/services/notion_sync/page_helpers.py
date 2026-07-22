"""Pure helpers for Notion page ingestion (no side effects on documents)."""

from __future__ import annotations

from typing import Iterable

from services.notion_sync.client import NotionClient, NotionPage


def fetch_block_tree(notion: NotionClient, block_id: str) -> Iterable[dict]:
    """Yield blocks and recursively attach children under `.children`."""
    for block in notion.iter_child_blocks(block_id):
        if block.get("has_children"):
            block["children"] = list(fetch_block_tree(notion, block["id"]))
        yield block


def ancestor_chain_titles(
    notion: NotionClient, page: NotionPage, mapped_root_page_id: str
) -> list[str]:
    """Titles from mapped-root-child down to (but excluding) `page`."""
    chain: list[str] = []
    current = page
    safety = 32
    while current.parent_page_id and current.parent_page_id != mapped_root_page_id and safety > 0:
        parent = notion.get_page(current.parent_page_id)
        chain.append(parent.title)
        current = parent
        safety -= 1
    chain.reverse()
    return chain
