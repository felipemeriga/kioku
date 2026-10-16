"""Unit tests for services.chunker — currently focused on build_contextual_header."""

import unittest

from services.chunker import build_contextual_header, contextualized_text


class TestContextualizedText(unittest.TestCase):
    def test_header_context_and_content(self):
        meta = {"source_filename": "a.pdf", "chunk_index": 0, "total_chunks": 2}
        out = contextualized_text(meta, "situates the chunk", "raw body")
        self.assertEqual(out, "Source: a.pdf | Chunk 1 of 2\nsituates the chunk\n\nraw body")

    def test_without_context_matches_bare_header_shape(self):
        # With no context the shape equals the legacy header + blank line + body,
        # so embed/rerank parity holds for pre-contextual chunks.
        meta = {"source_filename": "a.pdf", "chunk_index": 0, "total_chunks": 2}
        header = build_contextual_header(meta)
        self.assertEqual(contextualized_text(meta, None, "raw body"), f"{header}\n\nraw body")
        self.assertEqual(contextualized_text(meta, "", "raw body"), f"{header}\n\nraw body")


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

    def test_includes_notion_parent_path_when_present(self):
        from services.chunker import build_contextual_header

        header = build_contextual_header(
            {
                "source_filename": "Sprint planning",
                "notion_parent_path": "Cosm / Sprints",
            }
        )
        self.assertIn("Sprint planning", header)
        self.assertIn("Cosm / Sprints", header)

    def test_omits_notion_parent_path_when_absent(self):
        from services.chunker import build_contextual_header

        header = build_contextual_header({"source_filename": "x.md"})
        self.assertNotIn("Section:", header)


if __name__ == "__main__":
    unittest.main()
