"""Notion sync scheduler.

Owns the periodic tick that decides which configs are due for a sync and enqueues
notion_sync_task on the arq queue. All ingestion work happens in the queue.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

from arq import create_pool

from services.queue.jobs import create_job, get_active_job
from services.queue.settings import _redis_settings

logger = logging.getLogger(__name__)


async def sync_loop(get_supabase, poll_interval_seconds: int = 60) -> None:
    """Long-running task started in FastAPI lifespan."""
    logger.info("Notion sync scheduler started (tick every %ss)", poll_interval_seconds)
    pool = await create_pool(_redis_settings())
    try:
        while True:
            try:
                await _tick(get_supabase(), pool)
            except Exception:
                logger.exception("Notion sync tick failed")
            await asyncio.sleep(poll_interval_seconds)
    finally:
        await pool.close()


async def _tick(supabase, pool) -> None:
    now = datetime.now(timezone.utc)
    configs = supabase.table("notion_sync_configs").select("*").execute().data or []

    for cfg in _configs_due_for_fast_poll(configs, now=now):
        if get_active_job(supabase, kind="notion_sync", source_ref=cfg["id"]):
            continue
        job_id = create_job(
            supabase,
            user_id=cfg["user_id"],
            kind="notion_sync",
            source_ref=cfg["id"],
            root_folder_id=cfg["root_folder_id"],
        )
        await pool.enqueue_job(
            "notion_sync_task",
            {"job_id": job_id, "config_id": cfg["id"], "full_reconcile": False},
        )

    for cfg in _configs_due_for_full_recon(configs, now=now):
        if get_active_job(supabase, kind="notion_sync", source_ref=cfg["id"]):
            continue
        job_id = create_job(
            supabase,
            user_id=cfg["user_id"],
            kind="notion_sync",
            source_ref=cfg["id"],
            root_folder_id=cfg["root_folder_id"],
        )
        await pool.enqueue_job(
            "notion_sync_task",
            {"job_id": job_id, "config_id": cfg["id"], "full_reconcile": True},
        )


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
