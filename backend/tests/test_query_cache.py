"""Unit tests for services.query_cache — best-effort query-embedding cache."""

import unittest
from unittest.mock import MagicMock, patch

import services.query_cache as qc


class TestQueryCache(unittest.TestCase):
    def setUp(self):
        qc._broken = False  # reset the process-level disable flag between tests

    def test_get_returns_none_when_redis_unavailable(self):
        with patch("services.query_cache._redis", return_value=None):
            self.assertIsNone(qc.get_cached("voyage-3:query", "hello"))

    def test_set_then_get_round_trip(self):
        store: dict[str, str] = {}
        fake = MagicMock()
        fake.get.side_effect = lambda k: store.get(k)
        fake.set.side_effect = lambda k, v, ex=None: store.__setitem__(k, v)

        with patch("services.query_cache._redis", return_value=fake):
            qc.set_cached("voyage-3:query", "hello", [0.1, 0.2, 0.3])
            got = qc.get_cached("voyage-3:query", "hello")

        self.assertEqual(got, [0.1, 0.2, 0.3])

    def test_distinct_text_and_model_do_not_collide(self):
        store: dict[str, str] = {}
        fake = MagicMock()
        fake.get.side_effect = lambda k: store.get(k)
        fake.set.side_effect = lambda k, v, ex=None: store.__setitem__(k, v)

        with patch("services.query_cache._redis", return_value=fake):
            qc.set_cached("voyage-3:query", "a", [1.0])
            qc.set_cached("voyage-code-3:query", "a", [2.0])
            self.assertEqual(qc.get_cached("voyage-3:query", "a"), [1.0])
            self.assertEqual(qc.get_cached("voyage-code-3:query", "a"), [2.0])
            self.assertIsNone(qc.get_cached("voyage-3:query", "b"))

    def test_read_error_disables_and_returns_none(self):
        fake = MagicMock()
        fake.get.side_effect = RuntimeError("connection reset")

        with patch("services.query_cache._redis", return_value=fake):
            self.assertIsNone(qc.get_cached("voyage-3:query", "x"))
        self.assertTrue(qc._broken)  # stops trying for the rest of the process


if __name__ == "__main__":
    unittest.main()
