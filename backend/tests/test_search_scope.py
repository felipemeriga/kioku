import unittest
from unittest.mock import MagicMock, patch


class TestScopeFiltersReachRpc(unittest.TestCase):
    def _capture_rpc(self):
        sb = MagicMock()
        sb.rpc.return_value.execute.return_value.data = []
        return sb

    def test_vector_search_passes_folder_and_file_filters(self):
        from services.search import _vector_search

        sb = self._capture_rpc()
        with patch("services.search.get_supabase", return_value=sb):
            _vector_search(
                [0.0] * 1024,
                "u1",
                5,
                None,
                None,
                root_folder_id="root-1",
                folder_ids=["f1", "f2"],
                source_filename="notes.pdf",
            )
        params = sb.rpc.call_args.args[1]
        self.assertEqual(params["filter_folder_ids"], ["f1", "f2"])
        self.assertEqual(params["filter_source_filename"], "notes.pdf")
        self.assertEqual(params["filter_root_folder_id"], "root-1")

    def test_keyword_search_passes_folder_and_file_filters(self):
        from services.search import _keyword_search

        sb = self._capture_rpc()
        with patch("services.search.get_supabase", return_value=sb):
            _keyword_search(
                "query",
                "u1",
                5,
                None,
                None,
                folder_ids=["f1"],
                source_filename="notes.pdf",
            )
        params = sb.rpc.call_args.args[1]
        self.assertEqual(params["filter_folder_ids"], ["f1"])
        self.assertEqual(params["filter_source_filename"], "notes.pdf")

    def test_unscoped_search_sends_no_scope_params(self):
        from services.search import _vector_search

        sb = self._capture_rpc()
        with patch("services.search.get_supabase", return_value=sb):
            _vector_search([0.0] * 1024, "u1", 5, None, None)
        params = sb.rpc.call_args.args[1]
        self.assertNotIn("filter_folder_ids", params)
        self.assertNotIn("filter_source_filename", params)


class TestDescendantFolderIds(unittest.TestCase):
    def test_walks_subtree_breadth_first(self):
        from services.scope import descendant_folder_ids

        children = {
            ("root",): [{"id": "a"}, {"id": "b"}],
            ("a", "b"): [{"id": "a1"}],
            ("a1",): [],
        }

        sb = MagicMock()

        def _in(_field, frontier):
            chain = MagicMock()
            chain.eq.return_value.execute.return_value.data = children.get(tuple(frontier), [])
            return chain

        sb.table.return_value.select.return_value.in_.side_effect = _in

        ids = descendant_folder_ids(sb, "root", "u1")
        self.assertEqual(ids, ["root", "a", "b", "a1"])

    def test_leaf_folder_returns_itself(self):
        from services.scope import descendant_folder_ids

        sb = MagicMock()
        chain = sb.table.return_value.select.return_value.in_.return_value
        chain.eq.return_value.execute.return_value.data = []

        self.assertEqual(descendant_folder_ids(sb, "leaf", "u1"), ["leaf"])


class TestExecuteToolScope(unittest.TestCase):
    def test_scope_reaches_search_documents(self):
        from services.tools import execute_tool

        with (
            patch("services.tools.embed_query", return_value=[0.0] * 1024),
            patch("services.tools.search_documents", return_value=[]) as search_mock,
        ):
            execute_tool(
                "knowledge_base_search",
                {"query": "q"},
                "u1",
                scope_folder_ids=["f1", "f2"],
                scope_filename="doc.md",
            )
        kwargs = search_mock.call_args.kwargs
        self.assertEqual(kwargs["folder_ids"], ["f1", "f2"])
        self.assertEqual(kwargs["source_filename"], "doc.md")
