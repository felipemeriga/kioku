from unittest.mock import patch

from services.repo_graph import store


class Query:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        self.rows = [row for row in self.rows if row.get(key) == value]
        return self

    def in_(self, key, values):
        self.rows = [row for row in self.rows if row.get(key) in values]
        return self

    def ilike(self, key, pattern):
        needle = pattern.strip("%").lower()
        self.rows = [row for row in self.rows if needle in str(row.get(key, "")).lower()]
        return self

    def order(self, key):
        self.rows.sort(key=lambda row: (row.get(key) is None, row.get(key)))
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    def range(self, start, end):
        self.rows = self.rows[start : end + 1]
        return self

    def execute(self):
        return type("Result", (), {"data": self.rows})()


class Database:
    def __init__(self, symbols, edges):
        self.tables = {"repo_symbols": symbols, "repo_edges": edges}

    def table(self, name):
        return Query(self.tables[name][:])


def test_references_and_impact_exclude_structural_edges_and_fuzzy_targets():
    symbols = [
        {"folder_id": "f", "node_id": "fn", "symbol": "sample()"},
        {"folder_id": "f", "node_id": "caller", "symbol": "caller()"},
        {"folder_id": "f", "node_id": "file", "symbol": "sample.ts"},
        {"folder_id": "f", "node_id": "other", "symbol": "sampleOther()"},
    ]
    edges = [
        {
            "folder_id": "f",
            "src_node_id": "caller",
            "dst_node_id": "fn",
            "relation": "calls",
            "ref_file": "sample.ts",
            "ref_line": 2,
        },
        {
            "folder_id": "f",
            "src_node_id": "file",
            "dst_node_id": "fn",
            "relation": "contains",
            "ref_file": "sample.ts",
            "ref_line": 1,
        },
        {
            "folder_id": "f",
            "src_node_id": "other",
            "dst_node_id": "other",
            "relation": "calls",
            "ref_file": "sample.ts",
            "ref_line": 3,
        },
    ]
    db = Database(symbols, edges)
    assert [
        r["src_node_id"] for r in store.find_references(db, folder_id="f", symbol="sample")
    ] == ["caller"]
    assert [r["node_id"] for r in store.impact_of(db, folder_id="f", symbol="sample")] == ["caller"]
    assert store.find_references(db, folder_id="f", symbol="sam") == []


def test_references_skip_deleted_sources_before_limit():
    symbols = [
        {"folder_id": "f", "node_id": "fn", "symbol": "sample()"},
        {"folder_id": "f", "node_id": "live", "symbol": "caller()"},
    ]
    edges = [
        {
            "folder_id": "f",
            "src_node_id": "deleted",
            "dst_node_id": "fn",
            "relation": "calls",
            "ref_file": "a.ts",
            "ref_line": 1,
        },
        {
            "folder_id": "f",
            "src_node_id": "live",
            "dst_node_id": "fn",
            "relation": "calls",
            "ref_file": "b.ts",
            "ref_line": 2,
        },
    ]
    assert [
        r["src_node_id"]
        for r in store.find_references(
            Database(symbols, edges), folder_id="f", symbol="sample", limit=1
        )
    ] == ["live"]


def test_definition_and_outline():
    rows = [
        {
            "folder_id": "f",
            "node_id": "one",
            "symbol": "sample()",
            "file": "src/a.ts",
            "start_line": 1,
        },
        {
            "folder_id": "f",
            "node_id": "two",
            "symbol": "sampleOther()",
            "file": "src/b.ts",
            "start_line": 2,
        },
    ]
    db = Database(rows, [])
    assert [r["node_id"] for r in store.find_definition(db, folder_id="f", symbol="sample()")] == [
        "one"
    ]
    assert [r["node_id"] for r in store.outline(db, folder_id="f", path="src/")] == ["one", "two"]


def test_direct_agent_graph_lookup_dispatches_all_operations():
    from services.tools import _code_graph_lookup

    row = {
        "node_id": "n",
        "symbol": "sample()",
        "kind": "function",
        "file": "a.ts",
        "start_line": 1,
        "depth": 1,
        "relation": "calls",
        "ref_file": "b.ts",
        "ref_line": 2,
    }
    with (
        patch("services.tools.get_supabase", return_value=Database([], [])),
        patch("services.tools._folder_names", return_value={"f": "repo"}),
        patch("services.tools.graph_store.find_definition", return_value=[row]) as definition,
        patch("services.tools.graph_store.find_references", return_value=[row]) as references,
        patch("services.tools.graph_store.outline", return_value=[row]) as outline,
        patch("services.tools.graph_store.impact_of", return_value=[row]) as impact,
    ):
        for operation, mock in [
            ("definition", definition),
            ("references", references),
            ("outline", outline),
            ("impact", impact),
        ]:
            result = _code_graph_lookup(
                {"operation": operation, "symbol": "sample", "path": "a.ts"}, ["f"]
            )
            assert "[repo]" in result
            assert mock.call_count == 1


def test_mcp_graph_tools_dispatch_and_render():
    import mcp_server

    row = {
        "node_id": "n",
        "symbol": "sample()",
        "kind": "function",
        "file": "a.ts",
        "start_line": 1,
        "depth": 1,
        "relation": "calls",
        "ref_file": "b.ts",
        "ref_line": 2,
    }
    token = mcp_server._current_user_id.set("u")
    try:
        with (
            patch("mcp_server.get_supabase", return_value=Database([], [])),
            patch("mcp_server._resolve_repo", return_value=("f", "repo")),
            patch("services.repo_graph.find_definition", return_value=[row]) as definition,
            patch("services.repo_graph.find_references", return_value=[row]) as references,
            patch("services.repo_graph.outline", return_value=[row]) as outline,
            patch("services.repo_graph.impact_of", return_value=[row]) as impact,
        ):
            for name, argument, mock in [
                ("find_definition", "sample", definition),
                ("find_references", "sample", references),
                ("outline", "a.ts", outline),
                ("impact_of", "sample", impact),
            ]:
                result = getattr(mcp_server, name)(argument)
                assert "a.ts" in result or "b.ts" in result
                assert mock.call_count == 1
    finally:
        mcp_server._current_user_id.reset(token)
