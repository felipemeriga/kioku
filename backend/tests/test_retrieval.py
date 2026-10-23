"""Document/code retrieval remains available without a memory service."""

from unittest.mock import MagicMock

import pytest

from services import retrieval


@pytest.mark.asyncio
async def test_retrieval_preserves_scope_filters_and_logs(monkeypatch):
    sb = MagicMock()
    monkeypatch.setattr(retrieval, "_resolve_root_folder_id", lambda *_: "workspace")
    search = MagicMock(
        return_value=[
            {
                "id": "chunk1",
                "content": "source",
                "similarity": 0.9,
                "created_at": "2026-10-23",
                "metadata": {"source_type": "code"},
            }
        ]
    )
    monkeypatch.setattr(retrieval, "search_documents", search)
    result = await retrieval.retrieve_knowledge(
        sb,
        embedding=[0.1],
        query_text="question",
        user_id="u1",
        folder_id="repo",
        folder_ids=["subtree"],
        source_filename="main.py",
        created_after="2026-10-01",
        created_before="2026-10-23",
        limit=5,
        channel="cli",
    )
    assert result.hits[0].source == "docs"
    assert result.hits[0].metadata["created_at"] == "2026-10-23"
    assert result.sources_hit[0]["source"] == "docs"
    search.assert_called_once_with(
        [0.1],
        query_text="question",
        user_id="u1",
        root_folder_id="workspace",
        fast_mode=True,
        top_k=5,
        folder_ids=["subtree"],
        source_filename="main.py",
        created_after="2026-10-01",
        created_before="2026-10-23",
    )
    sb.table.assert_called_once_with("retrieval_log")
    assert sb.table.return_value.insert.call_args.args[0]["channel"] == "cli"


@pytest.mark.asyncio
async def test_retrieval_handles_document_failure_without_external_fallback(monkeypatch):
    monkeypatch.setattr(retrieval, "_resolve_root_folder_id", lambda *_: "repo")
    monkeypatch.setattr(retrieval, "search_documents", MagicMock(side_effect=RuntimeError("down")))
    result = await retrieval.retrieve_knowledge(
        MagicMock(),
        embedding=[],
        query_text="question",
        user_id="u1",
        folder_id="repo",
    )
    assert result.hits == []
    assert [source["source"] for source in result.sources_hit] == ["docs"]


def test_retired_memory_surfaces_are_not_registered():
    import mcp_server
    from main import app

    paths = {route.path for route in app.routes}
    assert not any(path.startswith("/api/mem0") for path in paths)
    assert "/api/cli/session-capture" not in paths
    assert not hasattr(mcp_server, "save_memory")
    assert not hasattr(mcp_server, "search_memory")
    assert "/api/cli/search" in paths
