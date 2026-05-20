"""Unit tests for services.chunker — currently focused on build_contextual_header."""

import unittest

from services.chunker import build_contextual_header


class TestBuildContextualHeader(unittest.TestCase):
    def test_full_metadata(self):
        header = build_contextual_header(
            {
                "source_filename": "rag-paper.pdf",
                "topic": "retrieval augmented generation",
                "keywords": ["rag", "embeddings", "rerank"],
                "chunk_index": 2,
                "total_chunks": 10,
            }
        )
        self.assertEqual(
            header,
            "Source: rag-paper.pdf | Topic: retrieval augmented generation"
            " | Keywords: rag, embeddings, rerank | Chunk 3 of 10",
        )

    def test_skips_unknown_topic(self):
        header = build_contextual_header(
            {
                "source_filename": "x.txt",
                "topic": "unknown",
                "keywords": ["a"],
                "chunk_index": 0,
                "total_chunks": 1,
            }
        )
        self.assertNotIn("Topic:", header)
        self.assertIn("Keywords: a", header)

    def test_skips_empty_keywords(self):
        header = build_contextual_header(
            {
                "source_filename": "x.txt",
                "topic": "anything",
                "keywords": [],
                "chunk_index": 0,
                "total_chunks": 1,
            }
        )
        self.assertNotIn("Keywords:", header)

    def test_skips_chunk_position_when_missing(self):
        header = build_contextual_header({"source_filename": "x.txt"})
        self.assertEqual(header, "Source: x.txt")

    def test_uses_unknown_when_filename_missing(self):
        header = build_contextual_header({"chunk_index": 0, "total_chunks": 1})
        self.assertTrue(header.startswith("Source: unknown"))


if __name__ == "__main__":
    unittest.main()
