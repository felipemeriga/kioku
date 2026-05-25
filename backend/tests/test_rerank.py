"""Unit tests for services.rerank — verify scoring text matches indexed text."""

import unittest
from unittest.mock import MagicMock, patch


class TestRerankScoringText(unittest.TestCase):
    """The cross-encoder must score the same contextualized text that was indexed."""

    def test_scoring_text_includes_contextual_header(self):
        from services.rerank import _scoring_text

        doc = {
            "content": "Embeddings are dense vector representations of text.",
            "metadata": {
                "source_filename": "rag.pdf",
                "topic": "embeddings",
                "keywords": ["vector", "embed"],
                "chunk_index": 1,
                "total_chunks": 3,
            },
        }
        text = _scoring_text(doc)
        self.assertIn("Source: rag.pdf", text)
        self.assertIn("Topic: embeddings", text)
        self.assertIn("Keywords: vector, embed", text)
        self.assertIn("Chunk 2 of 3", text)
        self.assertIn("Embeddings are dense vector representations of text.", text)
        # Header must precede content with a blank line, matching ingestion.
        self.assertTrue(text.split("\n\n", 1)[0].startswith("Source:"))

    def test_scoring_text_handles_missing_metadata(self):
        from services.rerank import _scoring_text

        doc = {"content": "some text"}
        text = _scoring_text(doc)
        self.assertEqual(text, "Source: unknown\n\nsome text")

    def test_rerank_passes_contextualized_text_to_voyage(self):
        from services.rerank import rerank

        documents = [
            {
                "content": "raw chunk content",
                "metadata": {
                    "source_filename": "a.pdf",
                    "topic": "alpha",
                    "keywords": ["foo"],
                    "chunk_index": 0,
                    "total_chunks": 1,
                },
            }
        ]

        mock_result = MagicMock()
        mock_result.results = [MagicMock(index=0, relevance_score=0.9)]
        mock_voyage = MagicMock()
        mock_voyage.rerank.return_value = mock_result

        with patch("services.rerank._get_client", return_value=mock_voyage):
            rerank("what is alpha?", documents, top_k=1)

        passed_texts = mock_voyage.rerank.call_args.kwargs["documents"]
        self.assertEqual(len(passed_texts), 1)
        self.assertIn("Source: a.pdf", passed_texts[0])
        self.assertIn("Topic: alpha", passed_texts[0])
        self.assertIn("raw chunk content", passed_texts[0])

    def test_rerank_returns_original_content_not_scored_text(self):
        """Header is for scoring only; the returned doc keeps the raw chunk."""
        from services.rerank import rerank

        documents = [
            {
                "id": "abc",
                "content": "raw chunk content",
                "metadata": {"source_filename": "a.pdf", "chunk_index": 0, "total_chunks": 1},
            }
        ]

        mock_result = MagicMock()
        mock_result.results = [MagicMock(index=0, relevance_score=0.9)]
        mock_voyage = MagicMock()
        mock_voyage.rerank.return_value = mock_result

        with patch("services.rerank._get_client", return_value=mock_voyage):
            out = rerank("q", documents, top_k=1)

        self.assertEqual(out[0]["content"], "raw chunk content")
        self.assertEqual(out[0]["rerank_score"], 0.9)


class TestRerankMetrics(unittest.TestCase):
    def test_records_kept_dropped_and_score_distribution(self):
        import os
        from unittest.mock import MagicMock, patch

        from services.metrics import collect_request
        from services.rerank import rerank

        # Five docs scored 0.9, 0.8, 0.5, 0.1, 0.05 — threshold 0.2 keeps top 3 only.
        fake_results = MagicMock()
        fake_results.results = [
            MagicMock(index=0, relevance_score=0.9),
            MagicMock(index=1, relevance_score=0.8),
            MagicMock(index=2, relevance_score=0.5),
            MagicMock(index=3, relevance_score=0.1),
            MagicMock(index=4, relevance_score=0.05),
        ]

        docs = [{"content": f"doc{i}", "metadata": {}} for i in range(5)]

        with patch.dict(os.environ, {"RAG_METRICS": "1"}):
            with patch("services.rerank._get_client") as get_client:
                get_client.return_value.rerank.return_value = fake_results
                with collect_request("test") as m:
                    out = rerank("query", docs, top_k=5)

        self.assertEqual(len(out), 3)
        stages = dict(m._stages)
        self.assertIn("rerank", stages)
        r = stages["rerank"]
        self.assertEqual(r["n_in"], 5)
        self.assertEqual(r["n_kept"], 3)
        self.assertEqual(r["n_dropped"], 2)
        # p50 of [0.9, 0.8, 0.5, 0.1, 0.05] ≈ 0.5
        self.assertAlmostEqual(r["score_p50"], 0.5, places=2)


if __name__ == "__main__":
    unittest.main()
