"""Notion sync engine — scheduler shell.

Task 10 will refactor `_tick` to enqueue arq jobs for each due config. For now
`_tick` is a no-op so the sync loop keeps ticking without doing legacy work.
Only the scheduling helpers (`_configs_due_for_*`, `_parse_ts`) are retained.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Iterable

logger = logging.getLogger(__name__)


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
    """No-op stub. Task 10 will replace this with arq job enqueueing."""
    return


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
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
