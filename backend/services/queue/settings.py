"""arq WorkerSettings and Redis connection wiring.

Run the worker with:
    uv run arq services.queue.settings.WorkerSettings

Env vars:
    REDIS_URL (default redis://localhost:6379/0)
    INGEST_WORKER_CONCURRENCY (default 10)
"""

from __future__ import annotations

import logging
import os

from arq import cron
from arq.connections import RedisSettings
from dotenv import load_dotenv

# Load .env so the arq worker process gets SUPABASE_URL, ANTHROPIC_API_KEY,
# etc. uvicorn's main.py loads it too — this makes both entry points work.
load_dotenv()

from services.queue.tasks import (  # noqa: E402 — env must load before task imports
    embed_and_store_batch_task,
    ingest_document_task,
    ingest_notion_page_task,
    notion_sync_task,
)

log = logging.getLogger(__name__)


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


async def _reap_stale_jobs(ctx: dict) -> None:
    """On worker boot, fail jobs orphaned by a previous crash/downtime so the UI
    un-sticks and new syncs aren't blocked by zombie 'active' rows."""
    from db.client import get_supabase
    from services.queue.jobs import fail_stale_jobs

    try:
        reaped = fail_stale_jobs(get_supabase())
        if reaped:
            log.info("reaped %d stale ingestion job(s) at startup", reaped)
    except Exception:  # noqa: BLE001 — never block worker boot on this
        log.exception("stale-job reaper failed at startup")


class WorkerSettings:
    """arq worker configuration. Discovered by `arq services.queue.settings.WorkerSettings`."""

    redis_settings = _redis_settings()
    functions = [
        embed_and_store_batch_task,
        ingest_document_task,
        ingest_notion_page_task,
        notion_sync_task,
    ]
    on_startup = _reap_stale_jobs
    # Also reap every 5 minutes so a job that goes stale while the worker is up
    # (no restart, no new enqueue) still self-heals.
    cron_jobs = [
        cron(_reap_stale_jobs, minute=set(range(0, 60, 5)), run_at_startup=False)
    ]
    max_jobs: int = int(os.environ.get("INGEST_WORKER_CONCURRENCY", "10"))
    job_timeout: int = 60 * 60  # 1 hour hard cap per task
    keep_result: int = 60 * 60 * 24  # 24h result retention
