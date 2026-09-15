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
from services.notion_sync.reconciliation import NotionPageSnapshot, diff_pages
from services.queue.batching import into_batches
from services.queue.jobs import (
    create_job,
    increment_processed_batches,
    increment_processed_pages,
    mark_completed,
    mark_failed,
    mark_running,
    set_total_batches,
    set_total_pages,
)

logger = logging.getLogger(__name__)

_METADATA_CONCURRENCY = int(os.environ.get("METADATA_CONCURRENCY", "20"))


async def embed_and_store_batch_task(ctx: dict, payload: dict) -> None:
    """
    payload = {
        "job_id": str,
        "row_template": dict,              # base row (documents columns) shared across chunks
        "metadata_base": dict = {},        # jsonb defaults merged with per-chunk metadata
        "chunks": list[str],               # up to 128 chunk texts
        "chunk_index_offset": int = 0,     # first chunk_index for upload/drop (not notion)
        "replace_existing_page": bool,     # notion re-ingest: delete the page's old rows
                                           # here, after embedding succeeds, not before
    }
    """
    job_id = payload["job_id"]
    chunks: list[str] = payload["chunks"]
    row_template: dict = payload["row_template"]
    metadata_base: dict = payload.get("metadata_base") or {}
    chunk_index_offset: int = payload.get("chunk_index_offset", 0)

    try:
        supabase = get_supabase_thread_safe()

        embeddings = await asyncio.to_thread(embed_batch, chunks)
        metadata_list = await _parallel_metadata(chunks)

        rows: list[dict[str, Any]] = []
        for i, (chunk, embedding, meta) in enumerate(
            zip(chunks, embeddings, metadata_list, strict=True)
        ):
            merged_meta = {
                **metadata_base,
                **(meta or {}),
                "chunk_index": chunk_index_offset + i,
            }
            row: dict[str, Any] = {
                **row_template,
                "content": chunk,
                "embedding": embedding,
                "metadata": merged_meta,
            }
            if row_template.get("source_type") != "notion":
                row["chunk_index"] = chunk_index_offset + i
            rows.append(row)

        if payload.get("replace_existing_page") and row_template.get("notion_page_id"):
            # Every fallible external call (Voyage, Anthropic) is behind us —
            # only now is it safe to drop the previous version of this page.
            await asyncio.to_thread(
                lambda: (
                    supabase.table("documents")
                    .delete()
                    .eq("user_id", row_template["user_id"])
                    .eq("root_folder_id", row_template["root_folder_id"])
                    .eq("notion_page_id", row_template["notion_page_id"])
                    .execute()
                )
            )

        if rows:
            await asyncio.to_thread(lambda: supabase.table("documents").insert(rows).execute())

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
    job_id = payload["job_id"]
    try:
        await _ingest_notion_page_task_impl(ctx, payload)
    except Exception as exc:
        logger.exception("ingest_notion_page_task failed for job %s", job_id)
        try:
            mark_failed(get_supabase_thread_safe(), job_id=job_id, error=str(exc))
        except Exception:
            logger.exception("Failed to mark page job %s as failed", job_id)
        raise


async def _ingest_notion_page_task_impl(ctx: dict, payload: dict) -> None:
    supabase = get_supabase_thread_safe()
    mark_running(supabase, job_id=payload["job_id"], current_step="parsing")
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

    def _delete_existing_rows() -> None:
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

    # The old rows for this page must not be deleted until the replacement
    # chunks are safely embedded — with an upfront delete, an embed failure
    # (bad API key, outage) destroys the only copy we have. For the common
    # single-batch page the batch task deletes right before inserting, after
    # every external call has succeeded. Multi-batch pages fall back to the
    # upfront delete: their batches run concurrently, and a deferred delete in
    # one batch would race the inserts of another.
    if len(batches) != 1:
        _delete_existing_rows()

    if not batches:
        # The page had no embeddable text (e.g. a container/index page whose
        # body is just child links). No embed batches will run, so nothing
        # would ever call increment_processed_batches to finalize this job —
        # it would hang at "embedding" forever and block the parent sync from
        # completing. Finalize here and cascade the page count to the parent.
        mark_completed(supabase, job_id=payload["job_id"])
        parent_id = payload.get("parent_job_id")
        if parent_id:
            increment_processed_pages(supabase, job_id=parent_id)
        return

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
                "replace_existing_page": len(batches) == 1,
            },
        )

    # NOTE: parent_job_id's processed_pages is bumped by the batch task via
    # increment_processed_batches when the last batch completes. Bumping here
    # would fire before the actual chunks are stored (giving false progress).


async def notion_sync_task(ctx: dict, payload: dict) -> None:
    """
    payload = {
        "job_id": str,
        "config_id": str,
        "full_reconcile": bool,
    }
    """
    job_id = payload["job_id"]
    try:
        await _notion_sync_task_impl(ctx, payload)
    except Exception as exc:
        logger.exception("notion_sync_task failed for job %s", job_id)
        try:
            mark_failed(get_supabase_thread_safe(), job_id=job_id, error=str(exc))
        except Exception:
            logger.exception("Failed to mark sync job %s as failed", job_id)
        raise


async def _notion_sync_task_impl(ctx: dict, payload: dict) -> None:
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
        mark_failed(supabase, job_id=payload["job_id"], error="config not found")
        return
    cfg = cfg_rows[0]
    mark_running(supabase, job_id=payload["job_id"])

    token = decrypt_secret(cfg["integration_token_encrypted"])
    notion = NotionClient(token)
    mapped_root = cfg["notion_page_id"]

    if payload.get("full_reconcile"):
        # Enumerate all pages under the mapped root via search API (returns
        # last_edited_time in the same call, no per-page get_page needed).
        reachable_snaps: list[NotionPageSnapshot] = []
        for page in notion.iter_pages_edited_since(None):
            if _is_under_root(notion, page, mapped_root):
                reachable_snaps.append(
                    NotionPageSnapshot(
                        page_id=page.page_id,
                        last_edited_time=page.last_edited_time,
                    )
                )

        # What's currently in DB for this root?
        db_page_map = _load_db_page_edit_map(
            supabase,
            user_id=cfg["user_id"],
            root_folder_id=cfg["root_folder_id"],
        )

        diff = diff_pages(reachable_snaps, db_page_map)
        page_ids = diff.to_ingest

        # Hard-delete pages that disappeared from Notion — but verify each one
        # against the live API first. Search-index lag once tombstoned ~18
        # perfectly healthy pages right after a reorg; never again.
        if diff.to_tombstone:
            confirmed = [
                pid for pid in diff.to_tombstone if _confirmed_gone(notion, pid, mapped_root)
            ]
            skipped = len(diff.to_tombstone) - len(confirmed)
            if skipped:
                logger.warning(
                    "full reconciliation: kept %d page(s) the search API missed "
                    "but that are still under the root",
                    skipped,
                )
            if confirmed:
                _remove_pages(
                    supabase,
                    user_id=cfg["user_id"],
                    root_folder_id=cfg["root_folder_id"],
                    page_ids=confirmed,
                )
                logger.info("full reconciliation: removed %d pages", len(confirmed))
    else:
        since = _parse_ts(cfg.get("last_fast_sync_at"))
        page_ids = []
        for page in notion.iter_pages_edited_since(since):
            if _is_under_root(notion, page, mapped_root):
                page_ids.append(page.page_id)

    set_total_pages(supabase, job_id=payload["job_id"], total=len(page_ids))

    # If no pages to process (fast poll with no recent edits, or full reconcile
    # with no changes), mark the sync job completed immediately — no child jobs
    # will ever fire increment.
    if not page_ids:
        mark_completed(supabase, job_id=payload["job_id"])

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

    # Advance the sync timestamp with a 60s buffer for fast poll, to account for
    # Notion search-index lag. Without the buffer, a page edited RIGHT before we
    # queried search may not appear in this run's results, and the next fast poll
    # would skip past its last_edited_time. Reconciliation catches missed pages
    # eventually, but a slight buffer here makes fast poll more reliable.
    from datetime import timedelta

    if payload.get("full_reconcile"):
        watermark = datetime.now(timezone.utc)
        col = "last_full_sync_at"
    else:
        watermark = datetime.now(timezone.utc) - timedelta(seconds=60)
        col = "last_fast_sync_at"
    (
        supabase.table("notion_sync_configs")
        .update({col: watermark.isoformat(), "last_error": None})
        .eq("id", cfg["id"])
        .execute()
    )


def _resolve_parent_page_id(notion: "NotionClient", page: NotionPage) -> str | None:
    """Return the id of the page containing `page`, walking through any
    intermediate blocks (columns, toggles…) the page may be nested in."""
    if page.parent_page_id:
        return page.parent_page_id
    block_id = page.parent_block_id
    safety = 16
    while block_id and safety > 0:
        parent = notion.get_block_parent(block_id)
        if parent.get("type") == "page_id":
            return parent.get("page_id")
        block_id = parent.get("block_id")
        safety -= 1
    return None


def _is_under_root(notion: "NotionClient", page: NotionPage, mapped_root: str) -> bool:
    if page.page_id == mapped_root:
        return False
    current = page
    safety = 32
    while safety > 0:
        parent_page_id = _resolve_parent_page_id(notion, current)
        if not parent_page_id:
            return False
        if parent_page_id == mapped_root:
            return True
        current = notion.get_page(parent_page_id)
        safety -= 1
    return False


def _confirmed_gone(notion: "NotionClient", page_id: str, mapped_root: str) -> bool:
    """Double-check a tombstone candidate against the live page before hard
    deleting. The full-reconcile enumeration relies on Notion's search API,
    which is eventually consistent — right after pages are moved around it can
    omit pages that still exist under the root. Only pages that are really
    deleted, archived, or moved out of the root may be removed."""
    page = notion.get_page_or_none(page_id)
    if page is None:
        return True
    if page.archived:
        return True
    return not _is_under_root(notion, page, mapped_root)


def _load_db_page_edit_map(supabase, *, user_id: str, root_folder_id: str) -> dict[str, datetime]:
    """Return {notion_page_id: last_edited_time} for all Notion-sourced rows in the root."""
    rows = (
        supabase.table("documents")
        .select("notion_page_id,notion_last_edited_time")
        .eq("user_id", user_id)
        .eq("root_folder_id", root_folder_id)
        .eq("source_type", "notion")
        .eq("status", "completed")
        .execute()
        .data
    ) or []

    out: dict[str, datetime] = {}
    for r in rows:
        pid = r.get("notion_page_id")
        ts = _parse_ts(r.get("notion_last_edited_time"))
        if not pid or ts is None:
            continue
        # Multiple chunks share the same edit time — first-write wins is fine.
        if pid not in out:
            out[pid] = ts
    return out


def _remove_pages(supabase, *, user_id: str, root_folder_id: str, page_ids: list[str]) -> None:
    """Hard-delete all documents for the given notion_page_ids.

    Notion is the source of truth. If a page reappears in Notion later, the
    next reconcile treats it as new and re-ingests. Hard delete avoids the
    need for downstream consumers (search, folder view, MCP) to filter out
    tombstoned rows.
    """
    if not page_ids:
        return
    (
        supabase.table("documents")
        .delete()
        .eq("user_id", user_id)
        .eq("root_folder_id", root_folder_id)
        .in_("notion_page_id", page_ids)
        .execute()
    )


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
    s = str(value).replace("Z", "+00:00")
    # Postgres timestamptz can emit fractional seconds with any digit count.
    # Python 3.10 datetime.fromisoformat only accepts 0/3/6 — normalize to 6.
    import re

    m = re.match(r"^(.*T\d{2}:\d{2}:\d{2})\.(\d+)(.*)$", s)
    if m:
        prefix, frac, suffix = m.groups()
        frac = (frac + "000000")[:6]
        s = f"{prefix}.{frac}{suffix}"
    return datetime.fromisoformat(s)


async def ingest_document_task(ctx: dict, payload: dict) -> None:
    """Parse an uploaded document and enqueue embed batches.

    payload = {
        "job_id": str,
        "user_id": str,
        "folder_id": str | None,
        "root_folder_id": str | None,
        "storage_bucket": str,     # 'images' | 'audio' | 'documents'
        "storage_path": str,       # path inside the bucket
        "filename": str,
        "source_type": str,        # 'pdf' | 'markdown' | 'image' | 'audio' | ...
        "media_kind": str,         # 'image' | 'audio' | 'document'
        "media_url": str | None,   # public URL for UI download links
        "content_hash": str,
    }
    """
    from services.parser import extract_from_image, parse_document, transcribe_audio

    job_id = payload["job_id"]
    try:
        supabase = get_supabase_thread_safe()
        # Move off "queued" right away: the UI otherwise shows "uploading"
        # through the whole download+parse phase (minutes for a big PDF), which
        # is indistinguishable from a dead worker.
        mark_running(supabase, job_id=job_id, current_step="parsing")

        # Download file bytes
        bucket = supabase.storage.from_(payload["storage_bucket"])
        file_bytes = await asyncio.to_thread(bucket.download, payload["storage_path"])

        # Parse (CPU-bound — offload to thread)
        media_kind = payload["media_kind"]
        filename = payload["filename"]
        if media_kind == "image":
            text = await asyncio.to_thread(extract_from_image, file_bytes, filename)
        elif media_kind == "audio":
            text = await asyncio.to_thread(transcribe_audio, file_bytes, filename)
        else:
            text = await asyncio.to_thread(parse_document, file_bytes, filename)

        if not text or not text.strip():
            mark_completed(supabase, job_id=job_id)
            return

        chunks = chunk_text(text)
        if not chunks:
            mark_completed(supabase, job_id=job_id)
            return

        batches = list(into_batches(chunks, size=128))
        set_total_batches(supabase, job_id=job_id, total=len(batches))

        row_template: dict = {
            "user_id": payload["user_id"],
            "source_filename": filename,
            "source_type": payload["source_type"],
            "content_hash": payload["content_hash"],
            "status": "completed",
        }
        if payload.get("folder_id"):
            row_template["folder_id"] = payload["folder_id"]
        if payload.get("root_folder_id"):
            row_template["root_folder_id"] = payload["root_folder_id"]

        metadata_base: dict = {
            "source_filename": filename,
            "total_chunks": len(chunks),
        }
        if payload.get("media_url"):
            key = {
                "image": "image_url",
                "audio": "audio_url",
                "document": "file_url",
            }.get(media_kind, "file_url")
            metadata_base[key] = payload["media_url"]

        offset = 0
        for batch in batches:
            await ctx["redis"].enqueue_job(
                "embed_and_store_batch_task",
                {
                    "job_id": job_id,
                    "row_template": row_template,
                    "metadata_base": metadata_base,
                    "chunks": batch,
                    "chunk_index_offset": offset,
                },
            )
            offset += len(batch)
    except Exception as exc:
        logger.exception("ingest_document_task failed for job %s", job_id)
        try:
            mark_failed(get_supabase_thread_safe(), job_id=job_id, error=str(exc))
        except Exception:
            logger.exception("Failed to mark upload job %s as failed", job_id)
        raise


async def _parallel_metadata(chunks: list[str]) -> list[dict]:
    """Run extract_metadata(chunk) concurrently with a semaphore."""
    sem = asyncio.Semaphore(_METADATA_CONCURRENCY)

    async def _one(text: str) -> dict:
        async with sem:
            return (await asyncio.to_thread(extract_metadata, text)) or {}

    return await asyncio.gather(*(_one(c) for c in chunks))
