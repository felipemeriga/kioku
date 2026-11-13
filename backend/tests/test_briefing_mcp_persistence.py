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


@pytest.mark.asyncio
async def test_registered_mcp_briefing_read_uses_current_schema_snapshot():
    sections = empty_briefing()
    sections["overview"] = new_section("Authoritative fixture overview")
    latest = {"content": {"sections": sections}, "generated_at": "2026-11-04T00:00:00Z"}
    sb = MagicMock()
    freshness = sb.table.return_value.select.return_value.eq.return_value.limit.return_value
    freshness.execute.return_value.data = []
    user_token = mcp_server._current_user_id.set("owner")
    scope_token = mcp_server._current_scope_folder_id.set("repo")
    try:
        with (
            patch("mcp_server.get_supabase", return_value=sb),
            patch("mcp_server.resolve_focus_folder", return_value=("repo", "Fixture repository")),
            patch(
                "services.folder_summary.repo.get_folder",
                return_value={"kind": "repo", "name": "Fixture repository"},
            ),
            patch("services.folder_summary.repo.get_latest_summary", return_value=latest),
        ):
            # Exercise the SDK registry and async offload, not only the Python helper.
            result = await mcp_server.mcp.call_tool("get_folder_briefing", {"folder": "repo"})
        content = result[0] if isinstance(result, tuple) else result
        payload = json.loads(content[0].text)
        assert payload["sections"]["overview"]["content"] == "Authoritative fixture overview"
        assert payload["last_generated_at"] == "2026-11-04T00:00:00Z"
        assert payload["folder"] == "Fixture repository"
    finally:
        mcp_server._current_user_id.reset(user_token)
        mcp_server._current_scope_folder_id.reset(scope_token)


@pytest.mark.parametrize("nested", [True, False])
def test_orientation_omits_retired_documentation_from_both_context_copies(nested):
    sections = empty_briefing()
    sections["documentation"] = new_section("Legacy large document abstract")
    content = {"sections": sections} if nested else sections
    row = {"kind": "briefing", "content": content, "sections": sections}
    sb = MagicMock()
    query = sb.table.return_value.select.return_value.eq.return_value.eq.return_value
    query.order.return_value.limit.return_value.execute.return_value.data = [row]
    query.in_.return_value.order.return_value.limit.return_value.execute.return_value.data = []
    user_token = mcp_server._current_user_id.set("owner")
    scope_token = mcp_server._current_scope_folder_id.set("repo")
    try:
        with (
            patch("mcp_server.get_supabase", return_value=sb),
            patch("mcp_server.resolve_focus_folder", return_value=("repo", "Repository")),
        ):
            payload = json.loads(mcp_server.get_folder_orientation(folder="repo"))
        assert "documentation" not in payload["briefing"]["sections"]
        assert "Legacy large document abstract" not in json.dumps(payload)
        assert len(payload["briefing"]["sections"]) == 5
    finally:
        mcp_server._current_user_id.reset(user_token)
        mcp_server._current_scope_folder_id.reset(scope_token)
