"""Unit tests for services.metrics — per-request collector + grouped printer."""

import io
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr
from unittest.mock import patch


class TestRecordOutsideCollector(unittest.TestCase):
    """record() must be a safe no-op when no collector is active."""

    def test_record_outside_context_is_noop(self):
        from services.metrics import record

        # Should not raise even when no collect_request() is active.
        record("some_stage", n=5, score=0.7)


class TestCollectAndPrint(unittest.TestCase):
    """collect_request() prints a grouped [metrics] block on exit."""

    def test_prints_grouped_block(self):
        from services.metrics import collect_request, record

        buf = io.StringIO()
        with redirect_stderr(buf), patch.dict(os.environ, {"RAG_METRICS": "1"}):
            with collect_request("rag chat turn"):
                record("vector_search", per_variant=[20, 18], unique=35, avg_sim=0.71)
                record("rerank", n_in=35, n_kept=5, n_dropped=30)

        out = buf.getvalue()
        self.assertIn("[metrics] === rag chat turn ===", out)
        self.assertIn("vector_search:", out)
        self.assertIn("per_variant=[20, 18]", out)
        self.assertIn("unique=35", out)
        self.assertIn("avg_sim=0.71", out)
        self.assertIn("rerank:", out)
        self.assertIn("n_kept=5", out)

    def test_disabled_when_env_unset(self):
        from services.metrics import collect_request, record

        buf = io.StringIO()
        with redirect_stderr(buf), patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RAG_METRICS", None)
            with collect_request("rag chat turn"):
                record("vector_search", unique=5)

        # Disabled: no [metrics] block emitted.
        self.assertNotIn("[metrics]", buf.getvalue())


class TestThreadPoolPropagation(unittest.TestCase):
    """submit_with_context() must let workers see the active collector."""

    def test_worker_records_into_parent_collector(self):
        from services.metrics import collect_request, record, submit_with_context  # noqa: F401

        buf = io.StringIO()
        with redirect_stderr(buf), patch.dict(os.environ, {"RAG_METRICS": "1"}):
            with collect_request("test"):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    f1 = submit_with_context(pool, _worker_record, "vector_search", 10)
                    f2 = submit_with_context(pool, _worker_record, "keyword_search", 7)
                    f1.result()
                    f2.result()

        out = buf.getvalue()
        self.assertIn("vector_search: n=10", out)
        self.assertIn("keyword_search: n=7", out)

    def test_plain_submit_loses_collector(self):
        """Sanity: without submit_with_context, the worker's record is a no-op."""
        from services.metrics import collect_request, submit_with_context  # noqa: F401

        buf = io.StringIO()
        with redirect_stderr(buf), patch.dict(os.environ, {"RAG_METRICS": "1"}):
            with collect_request("test"):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(_worker_record, "lost_stage", 99).result()

        # collector is per-context; the worker thread had a fresh, empty context.
        self.assertNotIn("lost_stage", buf.getvalue())


def _worker_record(stage: str, n: int) -> None:
    """Module-level so ThreadPoolExecutor can pickle it (not required, but clean)."""
    from services.metrics import record

    record(stage, n=n)


if __name__ == "__main__":
    unittest.main()
