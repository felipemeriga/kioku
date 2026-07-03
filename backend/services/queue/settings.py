"""arq WorkerSettings and Redis connection wiring.

Run the worker with:
    uv run arq services.queue.settings.WorkerSettings

Env vars:
    REDIS_URL (default redis://localhost:6379/0)
    INGEST_WORKER_CONCURRENCY (default 10)
"""

from __future__ import annotations

import os

from arq.connections import RedisSettings

from services.queue.tasks import (
    embed_and_store_batch_task,
    ingest_notion_page_task,
    notion_sync_task,
)


def _redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))


class WorkerSettings:
    """arq worker configuration. Discovered by `arq services.queue.settings.WorkerSettings`."""

    redis_settings = _redis_settings()
    functions = [
        embed_and_store_batch_task,
        ingest_notion_page_task,
        notion_sync_task,
    ]
    max_jobs: int = int(os.environ.get("INGEST_WORKER_CONCURRENCY", "10"))
    job_timeout: int = 60 * 60  # 1 hour hard cap per task
    keep_result: int = 60 * 60 * 24  # 24h result retention
