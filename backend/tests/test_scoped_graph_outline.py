"""Scoped outline batching preserves the public per-folder rendering contract."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from services import tools
from services.repo_graph import store


def row(folder, line):
    return {
        "folder_id": folder,
        "node_id": str(line),
        "symbol": f"symbol-{line}",
        "kind": "function",
        "file": "src/a.ts",
        "start_line": line,
        "updated_at": "2026-11-09T12:00:00Z",
    }


@pytest.mark.parametrize("scope_filename", [None, "src/a.ts", "other.ts"])
@pytest.mark.parametrize("count", [0, 3, 500])
def test_outline_batch_matches_per_folder_output_and_limits(scope_filename, count):
    folders = ["second", "empty", "first"] + [f"empty-{i}" for i in range(16)]
    data = {
        "first": [row("first", i) for i in range(count)],
        "second": [row("second", i) for i in range(count)],
    }
    with (
        patch.object(tools, "get_supabase", return_value=object()),
        patch.object(tools, "_folder_names", return_value={f: f for f in folders}),
        patch.object(
            store, "outline", side_effect=lambda _sb, folder_id, path: data.get(folder_id, [])
        ) as old,
        patch.object(
            store, "outline_scope", return_value=[r for f in folders for r in data.get(f, [])]
        ) as scoped,
    ):
        args = {"operation": "outline", "path": "src/"}
        expected = tools._code_graph_lookup(args, folders, scope_filename)
        actual = tools._code_graph_lookup(args, folders, scope_filename, user_id="owner")
        assert actual == expected
        assert old.call_count == 19
        scoped.assert_called_once()
        assert scoped.call_args.kwargs == {
            "owner_id": "owner",
            "folder_ids": folders,
            "path": "src/",
        }


def test_scoped_outline_has_one_rpc_and_deduplicates_requested_folders():
    sb = Mock()
    sb.rpc.return_value.execute.return_value = SimpleNamespace(data=[row("first", 1)])
    assert store.outline_scope(
        sb, owner_id="owner", folder_ids=["first", "first"], path="Src_%"
    ) == [row("first", 1)]
    sb.rpc.assert_called_once_with(
        "repo_graph_outline_scope",
        {
            "p_owner": "owner",
            "p_folders": ["first"],
            "p_path": "Src_%",
            "p_limit": 500,
        },
    )


def test_execute_tool_forwards_authenticated_owner_to_graph_outline():
    with patch.object(tools, "_code_graph_lookup", return_value="outline") as lookup:
        assert (
            tools.execute_tool(
                "code_graph_lookup",
                {"operation": "outline", "path": "src/"},
                "owner",
                scope_folder_ids=["first"],
            )
            == "outline"
        )
        assert lookup.call_args.kwargs["user_id"] == "owner"


def test_exact_code_source_is_owner_folder_file_and_line_scoped():
    sb = Mock()
    query = sb.table.return_value.select.return_value
    query.eq.return_value = query
    query.in_.return_value = query
    query.lte.return_value = query
    query.gte.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.execute.return_value = SimpleNamespace(
        data=[
            {
                "id": "chunk-1",
                "folder_id": "allowed",
                "file": "src/service.py",
                "symbol": "start_service",
                "start_line": 10,
                "end_line": 20,
                "content": "def start_service():\n    return True",
                "file_hash": "revision-1",
            }
        ]
    )
    citations = Mock()
    citations.register_many.return_value = [4]
    retrieval = []
    with (
        patch.object(tools, "get_supabase", return_value=sb),
        patch.object(tools, "_folder_names", return_value={"allowed": "repo"}),
    ):
        result = tools._code_graph_lookup(
            {"operation": "source", "path": "src/service.py", "line": 12},
            ["allowed"],
            user_id="owner",
            citations=citations,
            debug_retrieval=retrieval,
        )
    sb.table.assert_called_once_with("code_chunks")
    assert query.eq.call_args_list[0].args == ("user_id", "owner")
    assert query.in_.call_args.args == ("folder_id", ["allowed"])
    assert query.eq.call_args_list[1].args == ("file", "src/service.py")
    query.lte.assert_called_once_with("start_line", 12)
    query.gte.assert_called_once_with("end_line", 12)
    assert "[4] Code: [repo] src/service.py:10-20" in result
    assert retrieval[0]["source_type"] == "code"
    cited = citations.register_many.call_args.args[0][0]
    assert cited["metadata"]["revision_id"] == "revision-1"
    assert cited["metadata"]["folder_id"] == "allowed"


@pytest.mark.parametrize(
    "args",
    [
        {"operation": "source", "path": "../secret.py", "line": 1},
        {"operation": "source", "path": "/etc/passwd", "line": 1},
        {"operation": "source", "path": "src/service.py", "line": 0},
        {"operation": "source", "path": "src/service.py", "line": True},
    ],
)
def test_exact_code_source_rejects_invalid_paths_and_lines_before_database(args):
    with patch.object(tools, "get_supabase") as sb:
        result = tools._code_graph_lookup(args, ["allowed"], user_id="owner")
    assert "needs a repository-relative" in result
    sb.assert_not_called()


def test_exact_code_source_cannot_escape_selected_file():
    with patch.object(tools, "get_supabase") as sb:
        result = tools._code_graph_lookup(
            {"operation": "source", "path": "src/other.py", "line": 10},
            ["allowed"],
            "src/selected.py",
            user_id="owner",
        )
    assert "outside this turn's selected-file scope" in result
    sb.assert_not_called()
