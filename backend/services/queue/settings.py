"""arq WorkerSettings and Redis connection wiring.

Run the worker with:
    uv run arq services.queue.settings.WorkerSettings

Env vars:
    REDIS_URL (default redis://localhost:6379/0)
    INGEST_WORKER_CONCURRENCY (default 10)
"""

from __future__ import annotations

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
    nightly_folder_summary_scan,
    notion_sync_task,
    summarize_folder_task,
)


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


# Nightly folder-summary cron (UTC). Override via FOLDER_SUMMARY_CRON_HOUR /
# FOLDER_SUMMARY_CRON_MINUTE for local testing.
_CRON_HOUR = int(os.environ.get("FOLDER_SUMMARY_CRON_HOUR", "6"))
_CRON_MINUTE = int(os.environ.get("FOLDER_SUMMARY_CRON_MINUTE", "0"))


class WorkerSettings:
    """arq worker configuration. Discovered by `arq services.queue.settings.WorkerSettings`."""

    redis_settings = _redis_settings()
    functions = [
        embed_and_store_batch_task,
        ingest_document_task,
        ingest_notion_page_task,
        notion_sync_task,
        summarize_folder_task,
    ]
    cron_jobs = [
        cron(
            nightly_folder_summary_scan,
            hour={_CRON_HOUR},
            minute={_CRON_MINUTE},
            run_at_startup=False,
        ),
    ]
    max_jobs: int = int(os.environ.get("INGEST_WORKER_CONCURRENCY", "10"))
    job_timeout: int = 60 * 60  # 1 hour hard cap per task
    keep_result: int = 60 * 60 * 24  # 24h result retention
