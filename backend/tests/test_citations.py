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


class TestGithubBlobUrl(unittest.TestCase):
    def test_ssh_remote_to_https_blob(self):
        from services.citations import github_blob_url

        self.assertEqual(
            github_blob_url("git@github.com:felipemeriga/hive.git", "main", "backend/app.py", 10),
            "https://github.com/felipemeriga/hive/blob/main/backend/app.py#L10",
        )

    def test_https_remote_strips_dot_git(self):
        from services.citations import github_blob_url

        self.assertEqual(
            github_blob_url("https://github.com/org/repo.git", "dev", "pkg/x.py", None),
            "https://github.com/org/repo/blob/dev/pkg/x.py",
        )

    def test_defaults_branch_to_main_and_handles_leading_slash(self):
        from services.citations import github_blob_url

        self.assertEqual(
            github_blob_url("https://github.com/org/repo", None, "/pkg/x.py", 3),
            "https://github.com/org/repo/blob/main/pkg/x.py#L3",
        )

    def test_non_github_remote_returns_none(self):
        from services.citations import github_blob_url

        self.assertIsNone(github_blob_url("git@gitlab.com:org/repo.git", "main", "x.py", 1))
        self.assertIsNone(github_blob_url(None, "main", "x.py", 1))


class _FakeQuery:
    """Minimal supabase query-builder stub capturing the filter chain."""

    def __init__(self, rows, calls):
        self._rows = rows
        self._calls = calls

    def select(self, *a):
        return self

    def eq(self, col, val):
        self._calls["eq"] = (col, val)
        return self

    def in_(self, col, vals):
        self._calls["in_"] = (col, list(vals))
        return self

    def execute(self):
        return type("R", (), {"data": self._rows})()


class _FakeSupabase:
    def __init__(self, rows):
        self._rows = rows
        self.calls: dict = {}

    def table(self, name):
        self.calls["table"] = name
        return _FakeQuery(self._rows, self.calls)


class TestEnrichUrls(unittest.TestCase):
    def _code(self, loc, folder_id):
        return {
            "source_type": "code",
            "content": "code",
            "metadata": {"source_filename": loc, "folder_id": folder_id},
        }

    def test_fills_github_url_for_code_scoped_to_user(self):
        from services.citations import CitationRegistry

        reg = CitationRegistry()
        reg.register(self._code("backend/app.py:10-20", "f1"))
        reg.register(self._code("pkg/x.py:5-9", "f2"))

        sb = _FakeSupabase(
            [
                {"folder_id": "f1", "remote_url": "git@github.com:org/repo.git", "branch": "main"},
                {
                    "folder_id": "f2",
                    "remote_url": "https://github.com/org/other.git",
                    "branch": "dev",
                },
            ]
        )
        reg.enrich_urls(sb, "u1")

        a, b = reg.entries()
        self.assertEqual(a["url"], "https://github.com/org/repo/blob/main/backend/app.py#L10")
        self.assertEqual(b["url"], "https://github.com/org/other/blob/dev/pkg/x.py#L5")
        # Query is scoped to the caller's user_id (service key bypasses RLS).
        self.assertEqual(sb.calls["eq"], ("user_id", "u1"))
        self.assertEqual(sb.calls["table"], "watched_repos")
        self.assertEqual(set(sb.calls["in_"][1]), {"f1", "f2"})

    def test_missing_repo_leaves_url_none_and_is_idempotent(self):
        from services.citations import CitationRegistry

        reg = CitationRegistry()
        reg.register(self._code("backend/app.py:10-20", "f1"))
        sb = _FakeSupabase([])  # no matching watched_repos row
        reg.enrich_urls(sb, "u1")
        self.assertIsNone(reg.entries()[0]["url"])
        # A second call is a no-op (does not re-query).
        sb2 = _FakeSupabase(
            [{"folder_id": "f1", "remote_url": "git@github.com:o/r.git", "branch": "main"}]
        )
        reg.enrich_urls(sb2, "u1")
        self.assertNotIn("table", sb2.calls)

    def test_documents_are_untouched(self):
        from services.citations import CitationRegistry

        reg = CitationRegistry()
        reg.register(
            {
                "source_type": "document",
                "content": "x",
                "metadata": {"source_filename": "a.pdf", "folder_id": "f1"},
            }
        )
        reg.enrich_urls(_FakeSupabase([]), "u1")
        self.assertIsNone(reg.entries()[0]["url"])


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
