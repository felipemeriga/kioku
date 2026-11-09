import os
import unittest
from unittest.mock import patch


class TestRedisSettings(unittest.TestCase):
    def test_parses_redis_url(self):
        from services.queue.settings import _redis_settings

        with patch.dict(os.environ, {"REDIS_URL": "redis://kioku-redis:6379/0"}):
            settings = _redis_settings()

        self.assertEqual(settings.host, "kioku-redis")
        self.assertEqual(settings.port, 6379)
        self.assertEqual(settings.database, 0)

    def test_connection_timeouts_survive_load_spikes(self):
        """arq's default conn_timeout is 1s — a loaded host can exceed that on a
        plain TCP connect, which killed the worker mid-run (heart_beat →
        enqueue_job → TimeoutError has no retry wrapper). Give the connection
        generous timeout and retry budget instead."""
        from services.queue.settings import _redis_settings

        settings = _redis_settings()

        self.assertGreaterEqual(settings.conn_timeout, 10)
        self.assertGreaterEqual(settings.conn_retries, 5)
        self.assertGreaterEqual(settings.conn_retry_delay, 2)


class TestEvidenceMaintenanceSchedule(unittest.TestCase):
    def test_failed_sweep_does_not_block_later_scheduled_runs(self):
        from services.queue.settings import WorkerSettings

        maintenance = next(
            job for job in WorkerSettings.cron_jobs if job.name == "cron:agent_evidence_maintenance"
        )
        # arq derives a distinct, cross-worker unique ID from each scheduled
        # instant when job_id is unset. A retained failure at an earlier
        # instant must not suppress the next sweep.
        self.assertIsNone(maintenance.job_id)
        self.assertTrue(maintenance.unique)
        self.assertEqual(maintenance.keep_result_s, 0)
        self.assertEqual(maintenance.second, {0, 30})


class TestEvidenceCronRetryIdentity(unittest.IsolatedAsyncioTestCase):
    async def test_retained_failure_cannot_suppress_next_scheduled_sweep(self):
        from copy import deepcopy
        from datetime import datetime, timedelta, timezone
        from types import SimpleNamespace

        import fakeredis.aioredis
        from arq.connections import ArqRedis
        from arq.constants import default_queue_name, job_key_prefix, result_key_prefix
        from arq.worker import Worker

        from services.queue.settings import WorkerSettings

        fake = fakeredis.aioredis.FakeRedis()
        pool = ArqRedis(connection_pool=fake.connection_pool)
        cron = deepcopy(
            next(
                job
                for job in WorkerSettings.cron_jobs
                if job.name == "cron:agent_evidence_maintenance"
            )
        )
        start = datetime(2026, 11, 9, 20, 0, 0, 123456, tzinfo=timezone.utc)
        cron.next_run = start
        worker = SimpleNamespace(
            cron_jobs=[cron],
            pool=pool,
            queue_name=default_queue_name,
            timezone=timezone.utc,
        )
        try:
            await Worker.run_cron(worker, start, 0.5)
            (first,) = await pool.zrange(default_queue_name, 0, -1)
            first_id = first.decode()
            # Reproduce ARQ's retained result after an exhausted startup attempt.
            await pool.set(result_key_prefix + first_id, b"retained failure", ex=86400)
            await pool.delete(job_key_prefix + first_id)
            await pool.zrem(default_queue_name, first)
            await Worker.run_cron(worker, start + timedelta(seconds=30), 0.5)
            (later,) = await pool.zrange(default_queue_name, 0, -1)
            self.assertNotEqual(first, later)
            self.assertEqual(await pool.exists(result_key_prefix + first_id), 1)
            # Another worker at the same scheduled instant still deduplicates.
            duplicate_cron = deepcopy(cron)
            duplicate_cron.next_run = start + timedelta(seconds=30)
            duplicate = SimpleNamespace(
                cron_jobs=[duplicate_cron],
                pool=pool,
                queue_name=default_queue_name,
                timezone=timezone.utc,
            )
            await Worker.run_cron(duplicate, start + timedelta(seconds=30), 0.5)
            self.assertEqual(await pool.zcard(default_queue_name), 1)
        finally:
            await pool.aclose()
            await fake.aclose()
