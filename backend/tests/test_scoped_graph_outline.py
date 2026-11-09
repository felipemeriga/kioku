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
