import unittest
from unittest.mock import patch


class TestCitationRegistry(unittest.TestCase):
    def _doc(self, source, content="body", **meta):
        return {
            "source_type": "document",
            "content": content,
            "metadata": {"source_filename": source, **meta},
        }

    def _code(self, loc, content="code", symbol=None, folder_id=None):
        return {
            "source_type": "code",
            "content": content,
            "metadata": {
                "source_filename": loc,
                "code_symbol": symbol,
                "folder_id": folder_id,
            },
        }

    def test_distinct_sources_get_sequential_numbers(self):
        from services.citations import CitationRegistry

        reg = CitationRegistry()
        self.assertEqual(reg.register(self._doc("a.pdf")), 1)
        self.assertEqual(reg.register(self._doc("b.pdf")), 2)
        self.assertEqual(reg.register(self._code("x.py:1-9")), 3)

    def test_same_source_reuses_number_across_rounds(self):
        from services.citations import CitationRegistry

        reg = CitationRegistry()
        self.assertEqual(reg.register(self._doc("a.pdf", "chunk one")), 1)
        self.assertEqual(reg.register(self._doc("b.pdf")), 2)
        # A later chunk from the SAME document reuses its number, not a new one.
        self.assertEqual(reg.register(self._doc("a.pdf", "chunk two")), 1)
        # Different chunk ranges of the same code FILE collapse to one number.
        self.assertEqual(reg.register(self._code("x.py:1-9")), 3)
        self.assertEqual(reg.register(self._code("x.py:40-55")), 3)
        self.assertEqual([e["number"] for e in reg.entries()], [1, 2, 3])

    def test_entry_shape_for_document_and_code(self):
        from services.citations import CitationRegistry

        reg = CitationRegistry()
        reg.register(self._doc("a.pdf", "hello world", file_url="https://x/a.pdf", folder_id="f1"))
        reg.register(self._code("pkg/x.py:10-20", "def foo():", symbol="foo", folder_id="f2"))
        doc, code = reg.entries()

        self.assertEqual(doc["number"], 1)
        self.assertEqual(doc["source_type"], "document")
        self.assertEqual(doc["source"], "a.pdf")
        self.assertEqual(doc["url"], "https://x/a.pdf")
        self.assertEqual(doc["folder_id"], "f1")
        self.assertEqual(doc["excerpt"], "hello world")
        self.assertIsNone(doc["file"])
        self.assertIsNone(doc["line"])

        self.assertEqual(code["number"], 2)
        self.assertEqual(code["source_type"], "code")
        self.assertEqual(code["source"], "pkg/x.py:10-20")
        self.assertEqual(code["file"], "pkg/x.py")
        self.assertEqual(code["line"], 10)
        self.assertEqual(code["symbol"], "foo")
        self.assertEqual(code["folder_id"], "f2")
        self.assertIsNone(code["url"])


class TestExecuteToolCitations(unittest.TestCase):
    def test_header_prefixed_and_sources_registered(self):
        from services.citations import CitationRegistry
        from services.tools import execute_tool

        results = [
            {
                "source_type": "document",
                "content": "alpha",
                "created_at": "2026-01-02T00:00:00Z",
                "metadata": {"source_filename": "a.pdf"},
            },
            {
                "source_type": "code",
                "content": "def foo(): ...",
                "created_at": "2026-03-04T00:00:00Z",
                "metadata": {"source_filename": "pkg/x.py:10-20", "code_symbol": "foo"},
            },
        ]
        reg = CitationRegistry()
        with (
            patch("services.tools.embed_query", return_value=[0.0] * 1024),
            patch("services.tools.search_documents", return_value=results),
        ):
            out = execute_tool(
                "knowledge_base_search",
                {"query": "q"},
                "u1",
                citations=reg,
            )

        # Each chunk header is prefixed with its stable [N], no outer brackets.
        self.assertIn("[1] Source: a.pdf — 2026-01-02", out)
        self.assertIn("[2] Code: pkg/x.py:10-20 — foo — updated 2026-03-04", out)
        entries = reg.entries()
        self.assertEqual([e["number"] for e in entries], [1, 2])
        self.assertEqual(entries[0]["source"], "a.pdf")
        self.assertEqual(entries[1]["file"], "pkg/x.py")

    def test_without_registry_keeps_legacy_bracketed_header(self):
        from services.tools import execute_tool

        results = [
            {
                "source_type": "document",
                "content": "alpha",
                "created_at": "2026-01-02T00:00:00Z",
                "metadata": {"source_filename": "a.pdf"},
            }
        ]
        with (
            patch("services.tools.embed_query", return_value=[0.0] * 1024),
            patch("services.tools.search_documents", return_value=results),
        ):
            out = execute_tool("knowledge_base_search", {"query": "q"}, "u1")

        self.assertIn("[Source: a.pdf — 2026-01-02]", out)


if __name__ == "__main__":
    unittest.main()
