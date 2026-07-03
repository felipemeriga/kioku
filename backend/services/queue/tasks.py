"""arq task functions for ingestion queue.

Task boundaries:
- Producer tasks (notion_sync_task, ingest_notion_page_task) build chunk batches
  and enqueue embed_and_store_batch_task per batch.
- embed_and_store_batch_task does the heavy lifting: Voyage batch embed +
  parallel Haiku metadata + bulk INSERT + progress increment.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Iterable

# Import whichever supabase accessor exists in db/client.py. Preflight in the
# task instructions verifies which name is used.
try:
    from db.client import get_supabase_thread_safe  # type: ignore
except ImportError:  # pragma: no cover - fallback for older codebases
    from db.client import get_supabase as get_supabase_thread_safe  # type: ignore

from services.chunker import chunk_text
from services.crypto import decrypt_secret
from services.embeddings import embed_batch
from services.metadata import extract_metadata
from services.notion_sync.attachments import resolve_attachments
from services.notion_sync.blocks_to_markdown import blocks_to_markdown
from services.notion_sync.client import NotionClient, NotionPage
from services.notion_sync.folder_paths import ensure_notion_folder_path
from services.notion_sync.page_helpers import ancestor_chain_titles, fetch_block_tree
from services.queue.batching import into_batches
from services.queue.jobs import (
    create_job,
    increment_processed_batches,
    increment_processed_pages,
    mark_failed,
    set_total_batches,
    set_total_pages,
)

logger = logging.getLogger(__name__)

_METADATA_CONCURRENCY = int(os.environ.get("METADATA_CONCURRENCY", "20"))


async def embed_and_store_batch_task(ctx: dict, payload: dict) -> None:
    """
    payload = {
        "job_id": str,
        "row_template": dict,              # base row shared across chunks
        "chunks": list[str],               # up to 128 chunk texts
        "chunk_index_offset": int = 0,     # first chunk_index for upload/drop (not notion)
    }
    """
    job_id = payload["job_id"]
    chunks: list[str] = payload["chunks"]
    row_template: dict = payload["row_template"]
    chunk_index_offset: int = payload.get("chunk_index_offset", 0)

    try:
        supabase = get_supabase_thread_safe()

        embeddings = embed_batch(chunks)
        metadata_list = await _parallel_metadata(chunks)

        rows: list[dict[str, Any]] = []
        for i, (chunk, embedding, meta) in enumerate(
            zip(chunks, embeddings, metadata_list, strict=True)
        ):
            row: dict[str, Any] = {
                **row_template,
                "content": chunk,
                "embedding": embedding,
                "metadata": meta,
            }
            if row_template.get("source_type") != "notion":
                row["chunk_index"] = chunk_index_offset + i
            rows.append(row)

        if rows:
            supabase.table("documents").insert(rows).execute()

        increment_processed_batches(supabase, job_id=job_id)
    except Exception as exc:
        logger.exception("embed_and_store_batch_task failed for job %s", job_id)
        try:
            mark_failed(get_supabase_thread_safe(), job_id=job_id, error=str(exc))
        except Exception:
            logger.exception("Failed to mark job %s as failed after primary error", job_id)
        raise


async def ingest_notion_page_task(ctx: dict, payload: dict) -> None:
    """
    payload = {
        "job_id": str,
        "parent_job_id": str | None,
        "config_id": str,
        "user_id": str,
        "root_folder_id": str,
        "mapped_root_page_id": str,
        "page_id": str,
        "integration_token": str,   # decrypted
    }
    """
    supabase = get_supabase_thread_safe()
    notion = NotionClient(payload["integration_token"])
    page = notion.get_page(payload["page_id"])
    blocks = list(fetch_block_tree(notion, payload["page_id"]))

    markdown = blocks_to_markdown(blocks)
    markdown = resolve_attachments(markdown)

    titles = ancestor_chain_titles(notion, page, payload["mapped_root_page_id"])
    leaf_folder_id, parent_path = ensure_notion_folder_path(
        supabase,
        user_id=payload["user_id"],
        root_folder_id=payload["root_folder_id"],
        ancestor_titles=titles,
    )

    (
        supabase.table("documents")
        .delete()
        .eq("user_id", payload["user_id"])
        .eq("root_folder_id", payload["root_folder_id"])
        .eq("notion_page_id", payload["page_id"])
        .execute()
    )

    chunks = chunk_text(markdown)
    batches = list(into_batches(chunks, size=128))
    set_total_batches(supabase, job_id=payload["job_id"], total=len(batches))

    row_template = {
        "user_id": payload["user_id"],
        "root_folder_id": payload["root_folder_id"],
        "folder_id": leaf_folder_id,
        "source_filename": page.title,
        "source_type": "notion",
        "notion_page_id": page.page_id,
        "notion_last_edited_time": page.last_edited_time.isoformat(),
        "notion_parent_path": parent_path,
        "status": "completed",
    }

    for batch in batches:
        await ctx["redis"].enqueue_job(
            "embed_and_store_batch_task",
            {
                "job_id": payload["job_id"],
                "row_template": row_template,
                "chunks": batch,
            },
        )

    if payload.get("parent_job_id"):
        increment_processed_pages(supabase, job_id=payload["parent_job_id"])


async def notion_sync_task(ctx: dict, payload: dict) -> None:
    """
    payload = {
        "job_id": str,
        "config_id": str,
        "full_reconcile": bool,
    }
    """
    supabase = get_supabase_thread_safe()
    cfg_rows = (
        supabase.table("notion_sync_configs")
        .select("*")
        .eq("id", payload["config_id"])
        .execute()
        .data
    )
    if not cfg_rows:
        logger.error("notion_sync_task: config %s not found", payload["config_id"])
        return
    cfg = cfg_rows[0]

    token = decrypt_secret(cfg["integration_token_encrypted"])
    notion = NotionClient(token)
    mapped_root = cfg["notion_page_id"]

    if payload.get("full_reconcile"):
        page_ids = list(_walk_tree_pages(notion, mapped_root))
    else:
        since = _parse_ts(cfg.get("last_fast_sync_at"))
        page_ids = []
        for page in notion.iter_pages_edited_since(since):
            if _is_under_root(notion, page, mapped_root):
                page_ids.append(page.page_id)

    set_total_pages(supabase, job_id=payload["job_id"], total=len(page_ids))

    for pid in page_ids:
        page_job_id = create_job(
            supabase,
            user_id=cfg["user_id"],
            kind="notion_page",
            source_ref=pid,
            root_folder_id=cfg["root_folder_id"],
            parent_job_id=payload["job_id"],
        )
        await ctx["redis"].enqueue_job(
            "ingest_notion_page_task",
            {
                "job_id": page_job_id,
                "parent_job_id": payload["job_id"],
                "config_id": cfg["id"],
                "user_id": cfg["user_id"],
                "root_folder_id": cfg["root_folder_id"],
                "mapped_root_page_id": mapped_root,
                "page_id": pid,
                "integration_token": token,
            },
        )

    now = datetime.now(timezone.utc).isoformat()
    col = "last_full_sync_at" if payload.get("full_reconcile") else "last_fast_sync_at"
    (
        supabase.table("notion_sync_configs")
        .update({col: now, "last_error": None})
        .eq("id", cfg["id"])
        .execute()
    )


def _is_under_root(notion: "NotionClient", page: NotionPage, mapped_root: str) -> bool:
    if page.page_id == mapped_root:
        return False
    current = page
    safety = 32
    while current.parent_page_id and safety > 0:
        if current.parent_page_id == mapped_root:
            return True
        current = notion.get_page(current.parent_page_id)
        safety -= 1
    return False


def _walk_tree_pages(notion: "NotionClient", root_page_id: str) -> Iterable[str]:
    """Yield every descendant page id under root_page_id."""
    stack = [root_page_id]
    seen: set[str] = set()
    while stack:
        pid = stack.pop()
        for block in notion.iter_child_blocks(pid):
            if block.get("type") == "child_page":
                child_id = block["id"]
                if child_id not in seen:
                    seen.add(child_id)
                    yield child_id
                    stack.append(child_id)


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


async def _parallel_metadata(chunks: list[str]) -> list[dict]:
    """Run extract_metadata(chunk) concurrently with a semaphore."""
    sem = asyncio.Semaphore(_METADATA_CONCURRENCY)

    async def _one(text: str) -> dict:
        async with sem:
            return (await asyncio.to_thread(extract_metadata, text)) or {}

    return await asyncio.gather(*(_one(c) for c in chunks))
