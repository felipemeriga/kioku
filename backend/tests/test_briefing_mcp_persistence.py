import json
from unittest.mock import MagicMock, patch

import pytest

import mcp_server
from services.folder_summary.briefing_schema import empty_briefing, new_section


@pytest.mark.parametrize("tool", ["replace", "section", "documentation"])
def test_mcp_briefing_writes_use_shared_dedup(tool):
    sections = empty_briefing()
    sections["overview"] = new_section("same")
    sections["documentation"] = new_section(
        "abstract\n\nFull architecture docs available — call get_repo_documentation."
    )
    latest = {"content": {"sections": sections}, "content_hash": None}
    sb = MagicMock()
    user_token = mcp_server._current_user_id.set("u1")
    scope_token = mcp_server._current_scope_folder_id.set("f1")
    try:
        with (
            patch("mcp_server.get_supabase", return_value=sb),
            patch("mcp_server.resolve_focus_folder", return_value=("f1", "repo")),
            patch("services.folder_summary.repo.get_folder", return_value={"kind": "repo"}),
            patch("services.folder_summary.repo.get_latest_summary", return_value=latest),
            patch("services.folder_summary.persistence.get_latest_summary", return_value=latest),
        ):
            if tool == "replace":
                result = mcp_server.replace_folder_briefing(
                    json.dumps({"overview": "same"}), folder="repo"
                )
            elif tool == "section":
                result = mcp_server.update_folder_briefing_section(
                    "overview", '"same"', folder="repo"
                )
            else:
                result = mcp_server.save_repo_documentation("full doc", "abstract", folder="repo")
        assert not result.startswith("Error"), result
        # Full documentation is saved separately, but no duplicate briefing.
        assert all(call.args != ("folder_summaries",) for call in sb.table.call_args_list)
    finally:
        mcp_server._current_user_id.reset(user_token)
        mcp_server._current_scope_folder_id.reset(scope_token)
