"""Verify services.search emits the expected metric records at each stage."""

import os
import unittest
from unittest.mock import patch


def _fake_vec(doc_id: str, sim: float = 0.7) -> dict:
    return {
        "id": doc_id,
        "content": f"vec-{doc_id}",
        "metadata": {},
        "content_hash": "h",
        "similarity": sim,
    }


def _fake_kw(doc_id: str) -> dict:
    return {"id": doc_id, "content": f"kw-{doc_id}", "metadata": {}, "content_hash": "h"}


class TestSearchMetrics(unittest.TestCase):
    def test_full_search_records_all_stages(self):
        from services.metrics import collect_request
        from services.search import search_documents

        with patch.dict(os.environ, {"RAG_METRICS": "1"}):
            with (
                patch("services.search.embed_query", return_value=[0.2] * 1024),
                patch(
                    "services.search.rerank",
                    side_effect=lambda q, docs, top_k=5, **_: docs[:top_k],
                ),
                patch("services.search.rewrite_query", return_value="rewritten q"),
                patch("services.search.generate_multi_queries", return_value=["v1", "v2", "v3"]),
                patch(
                    "services.search._vector_search",
                    side_effect=lambda emb, *a, **kw: [_fake_vec("v1"), _fake_vec("v2")],
                ),
                patch(
                    "services.search._keyword_search",
                    side_effect=lambda text, *a, **kw: [_fake_kw("k1")],
                ),
                patch("services.search._expand_with_neighbors", side_effect=lambda r: r),
            ):
                with collect_request("test") as m:
                    search_documents(
                        query_embedding=[0.1] * 1024,
                        query_text="original",
                        fast_mode=False,
                    )

        stage_names = [s for s, _ in m._stages]
        self.assertIn("query_expansion", stage_names)
        self.assertIn("vector_search", stage_names)
        self.assertIn("keyword_search", stage_names)
        self.assertIn("rrf_fusion", stage_names)

        # query_expansion records n_variants and rewrite_changed_text
        qx = dict(m._stages)["query_expansion"]
        self.assertEqual(qx["n_variants"], 4)  # rewritten + 3 multi
        self.assertTrue(qx["rewrite_changed_text"])

    def test_fast_search_records_minimal_stages(self):
        from services.metrics import collect_request
        from services.search import search_documents

        with patch.dict(os.environ, {"RAG_METRICS": "1"}):
            with (
                patch(
                    "services.search.rerank",
                    side_effect=lambda q, docs, top_k=5, **_: docs[:top_k],
                ),
                patch(
                    "services.search._vector_search",
                    return_value=[_fake_vec("v1")],
                ),
                patch(
                    "services.search._keyword_search",
                    return_value=[_fake_kw("k1")],
                ),
                patch("services.search._expand_with_neighbors", side_effect=lambda r: r),
            ):
                with collect_request("test") as m:
                    search_documents(
                        query_embedding=[0.1] * 1024,
                        query_text="q",
                        fast_mode=True,
                    )

        stage_names = [s for s, _ in m._stages]
        # No query_expansion in fast mode
        self.assertNotIn("query_expansion", stage_names)
        self.assertIn("vector_search", stage_names)
        self.assertIn("keyword_search", stage_names)


if __name__ == "__main__":
    unittest.main()
