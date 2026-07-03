"""Ingest a single Notion page into the rag documents table.

Contract:
- Identity is (user_id, root_folder_id, notion_page_id).
- Ingest replaces all previous chunks for that identity in one shot.
- Reuses existing chunker + embeddings + metadata extraction.
"""

from __future__ import annotations

import logging
from typing import Iterable

from services.chunker import build_contextual_header, chunk_text
from services.embeddings import embed_document
from services.metadata import extract_metadata
from services.notion_sync.attachments import resolve_attachments
from services.notion_sync.blocks_to_markdown import blocks_to_markdown
from services.notion_sync.client import NotionClient, NotionPage
from services.notion_sync.folder_paths import ensure_notion_folder_path

logger = logging.getLogger(__name__)


def ingest_notion_page(
    supabase,
    *,
    notion: NotionClient,
    user_id: str,
    root_folder_id: str,
    mapped_root_page_id: str,
    page_id: str,
) -> dict:
    """Fetch a Notion page and (re)ingest its content as chunks. Returns stats."""
    page = notion.get_page(page_id)
    blocks = list(_fetch_block_tree(notion, page_id))

    markdown = blocks_to_markdown(blocks)
    markdown = resolve_attachments(markdown)

    ancestor_titles = _ancestor_chain_titles(notion, page, mapped_root_page_id)
    leaf_folder_id, parent_path = ensure_notion_folder_path(
        supabase,
        user_id=user_id,
        root_folder_id=root_folder_id,
        ancestor_titles=ancestor_titles,
    )

    _delete_existing_chunks(
        supabase, user_id=user_id, root_folder_id=root_folder_id, page_id=page_id
    )

    chunks = chunk_text(markdown)
    inserted = 0
    for chunk in chunks:
        header = build_contextual_header(
            {
                "source_filename": page.title,
                "notion_parent_path": parent_path,
            }
        )
        contextual = f"{header}\n{chunk}" if header else chunk
        metadata = extract_metadata(chunk) or {}
        embedding = embed_document(contextual)

        supabase.table("documents").insert(
            {
                "user_id": user_id,
                "root_folder_id": root_folder_id,
                "folder_id": leaf_folder_id,
                "source_filename": page.title,
                "source_type": "notion",
                "content": chunk,
                "embedding": embedding,
                "metadata": metadata,
                "notion_page_id": page.page_id,
                "notion_last_edited_time": page.last_edited_time.isoformat(),
                "notion_parent_path": parent_path,
                "status": "completed",
            }
        ).execute()
        inserted += 1

    return {"page_id": page.page_id, "chunks": inserted, "title": page.title}


def _fetch_block_tree(notion: NotionClient, block_id: str) -> Iterable[dict]:
    """Yield blocks and recursively attach children under `.children`."""
    for block in notion.iter_child_blocks(block_id):
        if block.get("has_children"):
            block["children"] = list(_fetch_block_tree(notion, block["id"]))
        yield block


def _ancestor_chain_titles(
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


def _delete_existing_chunks(supabase, *, user_id: str, root_folder_id: str, page_id: str) -> None:
    (
        supabase.table("documents")
        .delete()
        .eq("user_id", user_id)
        .eq("root_folder_id", root_folder_id)
        .eq("notion_page_id", page_id)
        .execute()
    )
