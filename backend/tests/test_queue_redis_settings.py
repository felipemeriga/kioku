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
