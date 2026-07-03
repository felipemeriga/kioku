"""Notion sync engine — fast poll, full reconciliation, background driver.

- fast_poll(cfg): incremental. Query recently-edited pages via Notion search;
  keep only those under the mapped root; re-ingest each.
- full_reconciliation(cfg): walk the whole tree under the mapped root; tombstone
  any docs whose page_id is no longer reachable.
- sync_loop(): asyncio background task started in FastAPI lifespan; every 60s
  fetches all configs, decides which are due, and runs them (via a thread so we
  don't block the loop).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

from services.crypto import decrypt_secret
from services.notion_sync.client import NotionClient, NotionPage
from services.notion_sync.ingest import ingest_notion_page

logger = logging.getLogger(__name__)


def fast_poll(supabase, notion: NotionClient, cfg: dict) -> dict:
    """Ingest all pages under the mapped root whose last_edited_time > last_fast_sync_at."""
    since = _parse_ts(cfg.get("last_fast_sync_at"))
    changed = notion.iter_pages_edited_since(since)
    processed = 0
    errors = 0
    mapped_root = cfg["notion_page_id"]

    for page in changed:
        if not _is_under_root(notion, page, mapped_root):
            continue
        try:
            ingest_notion_page(
                supabase,
                notion=notion,
                user_id=cfg["user_id"],
                root_folder_id=cfg["root_folder_id"],
                mapped_root_page_id=mapped_root,
                page_id=page.page_id,
            )
            processed += 1
        except Exception:
            logger.exception("fast_poll: failed to ingest page %s", page.page_id)
            errors += 1

    _update_sync_timestamp(supabase, cfg["id"], "last_fast_sync_at", errors=errors)
    return {"processed": processed, "errors": errors}


def full_reconciliation(supabase, notion: NotionClient, cfg: dict) -> dict:
    """Walk the tree, ingest changed pages, tombstone missing ones."""
    mapped_root = cfg["notion_page_id"]
    reachable_ids: set[str] = set()

    for page_id in _walk_tree_pages(notion, mapped_root):
        reachable_ids.add(page_id)
        try:
            ingest_notion_page(
                supabase,
                notion=notion,
                user_id=cfg["user_id"],
                root_folder_id=cfg["root_folder_id"],
                mapped_root_page_id=mapped_root,
                page_id=page_id,
            )
        except Exception:
            logger.exception("full_reconciliation: failed to ingest %s", page_id)

    existing = (
        supabase.table("documents")
        .select("notion_page_id")
        .eq("user_id", cfg["user_id"])
        .eq("root_folder_id", cfg["root_folder_id"])
        .eq("source_type", "notion")
        .execute()
    )
    existing_ids = {row["notion_page_id"] for row in (existing.data or [])}
    missing = existing_ids - reachable_ids
    for gone in missing:
        (
            supabase.table("documents")
            .update({"status": "deleted"})
            .eq("user_id", cfg["user_id"])
            .eq("root_folder_id", cfg["root_folder_id"])
            .eq("notion_page_id", gone)
            .execute()
        )

    _update_sync_timestamp(supabase, cfg["id"], "last_full_sync_at")
    return {"reachable": len(reachable_ids), "tombstoned": len(missing)}


async def sync_loop(get_supabase, poll_interval_seconds: int = 60) -> None:
    """Long-running task started in FastAPI lifespan. Never returns until cancelled."""
    logger.info("Notion sync loop started (tick every %ss)", poll_interval_seconds)
    while True:
        try:
            await asyncio.to_thread(_tick, get_supabase())
        except Exception:
            logger.exception("Notion sync loop tick failed")
        await asyncio.sleep(poll_interval_seconds)


def _tick(supabase) -> None:
    now = datetime.now(timezone.utc)
    configs = supabase.table("notion_sync_configs").select("*").execute().data or []
    for cfg in _configs_due_for_fast_poll(configs, now=now):
        client = NotionClient(decrypt_secret(cfg["integration_token_encrypted"]))
        fast_poll(supabase, client, cfg)
    for cfg in _configs_due_for_full_recon(configs, now=now):
        client = NotionClient(decrypt_secret(cfg["integration_token_encrypted"]))
        full_reconciliation(supabase, client, cfg)


def _configs_due_for_fast_poll(configs: Iterable[dict], *, now: datetime) -> list[dict]:
    out = []
    for cfg in configs:
        last = _parse_ts(cfg.get("last_fast_sync_at"))
        interval = timedelta(minutes=cfg.get("fast_poll_interval_min", 5))
        if last is None or (now - last) >= interval:
            out.append(cfg)
    return out


def _configs_due_for_full_recon(configs: Iterable[dict], *, now: datetime) -> list[dict]:
    out = []
    for cfg in configs:
        last = _parse_ts(cfg.get("last_full_sync_at"))
        interval = timedelta(hours=cfg.get("full_reconciliation_interval_hours", 24))
        if last is None or (now - last) >= interval:
            out.append(cfg)
    return out


def _is_under_root(notion: NotionClient, page: NotionPage, mapped_root: str) -> bool:
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


def _walk_tree_pages(notion: NotionClient, root_page_id: str) -> Iterable[str]:
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


def _update_sync_timestamp(supabase, cfg_id: str, column: str, *, errors: int = 0) -> None:
    now = datetime.now(timezone.utc).isoformat()
    update: dict = {column: now, "updated_at": now}
    if errors == 0:
        update["last_error"] = None
    (supabase.table("notion_sync_configs").update(update).eq("id", cfg_id).execute())
