from unittest.mock import MagicMock, patch

import pytest

from services.tools import execute_tool


@pytest.mark.parametrize(
    "operation,key",
    [("definition", "file"), ("references", "ref_file"), ("impact", "file"), ("outline", "file")],
)
def test_graph_results_cannot_leave_selected_file(operation, key):
    rows = [
        {
            "folder_id": "folder",
            key: "selected.py",
            "file": "selected.py",
            "symbol": "Selected",
            "kind": "function",
            "start_line": 1,
            "ref_line": 2,
            "relation": "calls",
            "depth": 1,
        },
        {
            "folder_id": "folder",
            key: "private.py",
            "file": "private.py",
            "symbol": "Private",
            "kind": "function",
            "start_line": 5,
            "ref_line": 6,
            "relation": "calls",
            "depth": 1,
        },
    ]
    names = {
        "definition": "find_definition",
        "references": "find_references",
        "impact": "impact_of",
        "outline": "outline_scope",
    }
    with (
        patch("services.tools.get_supabase"),
        patch("services.tools._folder_names", return_value={"folder": "repo"}),
        patch(f"services.tools.graph_store.{names[operation]}", return_value=rows),
    ):
        result = execute_tool(
            "code_graph_lookup",
            {"operation": operation, "symbol": "X", "path": "."},
            "owner",
            scope_folder_ids=["folder"],
            scope_filename="selected.py",
        )
    assert "selected.py" in result
    assert "private.py" not in result
    assert "Private" not in result


def test_native_semantic_search_enforces_authoritative_code_filename():
    hits = [
        {
            "id": name,
            "content": name,
            "source_type": "code",
            "metadata": {"source_filename": f"{name}.py:1-10", "folder_id": "folder"},
        }
        for name in ("selected", "private")
    ]
    sb = MagicMock()
    scoped = sb.table.return_value.select.return_value.eq.return_value.in_.return_value
    scoped.execute.return_value.data = [
        {"id": name, "file": f"{name}.py", "folder_id": "folder", "file_hash": name}
        for name in ("selected", "private")
    ]
    with (
        patch("services.tools.get_supabase", return_value=sb),
        patch("services.tools.embed_query"),
        patch("services.tools.search_documents", return_value=hits),
    ):
        result = execute_tool(
            "knowledge_base_search",
            {"query": "all files"},
            "owner",
            fast_mode=True,
            scope_folder_ids=["folder"],
            scope_filename="selected.py",
            full_debug=True,
        )
    assert "selected.py" in result
    assert "private.py" not in result
