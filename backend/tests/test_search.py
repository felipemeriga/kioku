"""Unit tests for services.search — verify parallel pipeline correctness.

We mock the underlying network-bound functions and assert that the right
calls happen in the right shapes. Timing-based parallelism assertions are
flaky in CI, so we test wiring instead of wall-clock.
"""

import unittest
from unittest.mock import patch


def _fake_vec(doc_id: str) -> dict:
    return {"id": doc_id, "content": f"vec-{doc_id}", "metadata": {}, "content_hash": "h"}


def _fake_kw(doc_id: str) -> dict:
    return {"id": doc_id, "content": f"kw-{doc_id}", "metadata": {}, "content_hash": "h"}


class TestHybridSearchParallel(unittest.TestCase):
    """_run_hybrid_search must invoke vector + keyword search both, in parallel."""

    def test_runs_vector_and_keyword(self):
        from services.search import _run_hybrid_search

        with (
            patch("services.search._vector_search", return_value=[_fake_vec("v1")]) as v_mock,
            patch("services.search._keyword_search", return_value=[_fake_kw("k1")]) as k_mock,
        ):
            vec, kw = _run_hybrid_search([0.1] * 1024, "hello", None, 20, None, None, None)

        v_mock.assert_called_once()
        k_mock.assert_called_once()
        self.assertEqual(vec, [_fake_vec("v1")])
        self.assertEqual(kw, [_fake_kw("k1")])

    def test_skips_keyword_when_no_text(self):
        from services.search import _run_hybrid_search

        with (
            patch("services.search._vector_search", return_value=[_fake_vec("v1")]),
            patch("services.search._keyword_search") as k_mock,
        ):
            vec, kw = _run_hybrid_search([0.1] * 1024, "", None, 20, None, None, None)

        k_mock.assert_not_called()
        self.assertEqual(vec, [_fake_vec("v1")])
        self.assertEqual(kw, [])

    def test_vector_failure_returns_empty_for_that_leg(self):
        from services.search import _run_hybrid_search

        with (
            patch("services.search._vector_search", side_effect=RuntimeError("db down")),
            patch("services.search._keyword_search", return_value=[_fake_kw("k1")]),
        ):
            vec, kw = _run_hybrid_search([0.1] * 1024, "q", None, 20, None, None, None)

        self.assertEqual(vec, [])
        self.assertEqual(kw, [_fake_kw("k1")])


class TestFullPipelineParallel(unittest.TestCase):
    """Full (non-fast) search_documents path: 4 variants run in parallel."""

    def _wire(self, rewrite_return="rewritten q", multi_return=("v1", "v2", "v3")):
        """Patch every external dep used by search_documents and return the mocks."""
        embed = patch("services.search.embed_query", return_value=[0.2] * 1024)
        rerank = patch(
            "services.search.rerank",
            side_effect=lambda q, docs, top_k=5, **_: docs[:top_k],
        )
        rewrite = patch("services.search.rewrite_query", return_value=rewrite_return)
        multi = patch("services.search.generate_multi_queries", return_value=list(multi_return))
        vec = patch(
            "services.search._vector_search",
            side_effect=lambda emb, *a, **kw: [_fake_vec(f"v-{id(emb) % 1000}")],
        )
        kw = patch(
            "services.search._keyword_search",
            side_effect=lambda text, *a, **kw: [_fake_kw(f"k-{hash(text) % 1000}")],
        )
        expand = patch("services.search._expand_with_neighbors", side_effect=lambda r: r)
        return embed, rerank, rewrite, multi, vec, kw, expand

    def test_runs_rewrite_and_multi_query_both(self):
        from services.search import search_documents

        e, rr, rw, mq, vec, kw, ex = self._wire()
        with e, rr, rw as rw_mock, mq as mq_mock, vec, kw, ex:
            search_documents(
                query_embedding=[0.1] * 1024,
                query_text="original question",
                fast_mode=False,
            )

        rw_mock.assert_called_once_with("original question")
        mq_mock.assert_called_once_with("original question")

    def test_runs_all_four_variants(self):
        """1 rewritten + 3 multi-query variants → 4 variant searches."""
        from services.search import search_documents

        e, rr, rw, mq, vec, kw, ex = self._wire()
        with e, rr, rw, mq, vec as vec_mock, kw as kw_mock, ex:
            search_documents(
                query_embedding=[0.1] * 1024,
                query_text="original question",
                fast_mode=False,
            )

        self.assertEqual(vec_mock.call_count, 4)
        self.assertEqual(kw_mock.call_count, 4)

    def test_reuses_precomputed_embedding_when_rewrite_unchanged(self):
        """If rewrite_query returns the same text, don't re-embed it."""
        from services.search import search_documents

        e, rr, rw, mq, vec, kw, ex = self._wire(
            rewrite_return="original question",  # unchanged
            multi_return=("v1", "v2", "v3"),
        )
        with e as e_mock, rr, rw, mq, vec, kw, ex:
            search_documents(
                query_embedding=[0.1] * 1024,
                query_text="original question",
                fast_mode=False,
            )

        # 3 additional variants need their own embed; the unchanged variant
        # reuses the precomputed embedding → 3 embed calls, not 4.
        self.assertEqual(e_mock.call_count, 3)

    def test_re_embeds_when_rewrite_changes_text(self):
        from services.search import search_documents

        e, rr, rw, mq, vec, kw, ex = self._wire(
            rewrite_return="DIFFERENT rewritten text",
            multi_return=("v1", "v2", "v3"),
        )
        with e as e_mock, rr, rw, mq, vec, kw, ex:
            search_documents(
                query_embedding=[0.1] * 1024,
                query_text="original question",
                fast_mode=False,
            )

        # rewritten variant + 3 multi-query variants all need embeds → 4
        self.assertEqual(e_mock.call_count, 4)

    def test_fast_mode_skips_rewrite_and_multi_query(self):
        from services.search import search_documents

        e, rr, rw, mq, vec, kw, ex = self._wire()
        with e, rr, rw as rw_mock, mq as mq_mock, vec as vec_mock, kw as kw_mock, ex:
            search_documents(
                query_embedding=[0.1] * 1024,
                query_text="q",
                fast_mode=True,
            )

        rw_mock.assert_not_called()
        mq_mock.assert_not_called()
        # Fast mode: one parallel hybrid search → 1 vector + 1 keyword call
        self.assertEqual(vec_mock.call_count, 1)
        self.assertEqual(kw_mock.call_count, 1)


class TestParallelSpeedup(unittest.TestCase):
    """Soft timing check — ensures we're not silently re-serializing the pipeline."""

    def test_hybrid_search_is_not_serial(self):
        """Vector + keyword each sleep 100ms; total should be ~100ms not ~200ms."""
        import time

        from services.search import _run_hybrid_search

        def slow_vec(*_args, **_kwargs):
            time.sleep(0.1)
            return [_fake_vec("v")]

        def slow_kw(*_args, **_kwargs):
            time.sleep(0.1)
            return [_fake_kw("k")]

        with (
            patch("services.search._vector_search", side_effect=slow_vec),
            patch("services.search._keyword_search", side_effect=slow_kw),
        ):
            t0 = time.monotonic()
            _run_hybrid_search([0.1] * 4, "q", None, 20, None, None, None)
            elapsed = time.monotonic() - t0

        # Parallel: ~0.10s. Serial would be ~0.20s. Allow generous margin.
        self.assertLess(elapsed, 0.18, f"hybrid search appears to be serial ({elapsed:.3f}s)")


if __name__ == "__main__":
    unittest.main()
