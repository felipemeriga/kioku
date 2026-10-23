"""Content changes, not duplicate uploads or sync touches, advance freshness."""

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import ingestion


def _database(rows):
    """Chainable fake records the exact scope used for reads/deletes."""
    sb = MagicMock()
    table = sb.table.return_value
    table.select.return_value = table
    table.eq.return_value = table
    table.is_.return_value = table
    table.order.return_value = table
    table.delete.return_value = table
    table.execute.return_value.data = rows
    table.insert.return_value.execute.return_value.data = [{"id": "new"}]
    return sb, table


@pytest.mark.parametrize("filename", ["api.pdf", "api.md"])
def test_duplicate_upload_does_not_parse_embed_or_update(filename):
    with (
        patch.object(ingestion, "check_duplicate", return_value=True),
        patch("services.parser.parse_document") as parse,
        patch("services.embeddings.embed_batch") as embed,
        patch.object(ingestion, "get_supabase") as database,
    ):
        assert ingestion.ingest_document(b"same", filename, "u1")["duplicate"]
    parse.assert_not_called()
    embed.assert_not_called()
    database.assert_not_called()


def test_identical_explicit_replace_preserves_rows_and_dates():
    rows = [
        {
            "id": "old",
            "content": "same",
            "content_hash": hashlib.sha256(b"same").hexdigest(),
            "created_at": "2025-01-01",
        }
    ]
    sb, table = _database(rows)
    with (
        patch.object(ingestion, "get_supabase", return_value=sb),
        patch("services.chunker.chunk_text", return_value=["same"]),
        patch("services.embeddings.embed_batch") as embed,
    ):
        result = ingestion.replace_document("same", "api.md", "u1", "f1")
    assert result["document_ids"] == ["old"]
    embed.assert_not_called()
    table.delete.assert_not_called()
    table.insert.assert_not_called()
    table.eq.assert_any_call("user_id", "u1")
    table.eq.assert_any_call("folder_id", "f1")


@pytest.mark.parametrize("folder_id", [None, "f1"])
def test_changed_explicit_replace_preserves_creation_and_shares_update_time(folder_id):
    sb, table = _database(
        [{"id": "old", "content": "previous", "created_at": "2025-01-01T00:00:00Z"}]
    )
    with (
        patch.object(ingestion, "get_supabase", return_value=sb),
        patch("services.chunker.chunk_text", return_value=["new 1", "new 2"]),
        patch("services.contextual.contextualize_chunks", return_value=["", ""]),
        patch("services.embeddings.embed_batch", return_value=[[0.1], [0.2]]),
        patch("services.scope.resolve_root_folder_id", return_value="root"),
    ):
        ingestion.replace_document("new body", "api.md", "u1", folder_id)
    inserted = [call.args[0] for call in table.insert.call_args_list]
    assert len(inserted) == 2
    assert {row["created_at"] for row in inserted} == {"2025-01-01T00:00:00Z"}
    assert len({row["last_updated"] for row in inserted}) == 1
    assert inserted[0]["last_updated"] > inserted[0]["created_at"]
    if folder_id is None:
        # An unfiled document must not replace files with the same name in
        # arbitrary folders belonging to this user.
        table.is_.assert_any_call("folder_id", "null")
    else:
        table.eq.assert_any_call("folder_id", folder_id)


def test_failed_replace_embedding_keeps_old_document():
    sb, table = _database([{"id": "old", "content": "previous"}])
    with (
        patch.object(ingestion, "get_supabase", return_value=sb),
        patch("services.chunker.chunk_text", return_value=["new"]),
        patch("services.contextual.contextualize_chunks", return_value=[""]),
        patch("services.embeddings.embed_batch", side_effect=RuntimeError("unavailable")),
        pytest.raises(RuntimeError),
    ):
        ingestion.replace_document("new", "api.md", "u1", "f1")
    table.delete.assert_not_called()
    table.insert.assert_not_called()


def test_upload_queue_shares_one_timestamp_across_batches():
    from services.queue import tasks

    sb = MagicMock()
    sb.storage.from_.return_value.download.return_value = b"file"
    redis = MagicMock(enqueue_job=AsyncMock())
    payload = {
        "job_id": "j1",
        "user_id": "u1",
        "storage_bucket": "documents",
        "storage_path": "p",
        "filename": "api.pdf",
        "media_kind": "document",
        "source_type": "pdf",
        "content_hash": "hash",
    }
    with (
        patch.object(tasks, "get_supabase_thread_safe", return_value=sb),
        patch.object(tasks, "mark_running"),
        patch.object(tasks, "set_total_batches"),
        patch("services.parser.parse_document", return_value="full text"),
        patch.object(tasks, "chunk_text", return_value=["chunk"] * 129),
        patch.object(tasks, "contextualize_chunks", return_value=[""] * 129),
    ):
        asyncio.run(tasks.ingest_document_task({"redis": redis}, payload))
    templates = [call.args[1]["row_template"] for call in redis.enqueue_job.call_args_list]
    assert len(templates) == 2
    assert len({row["last_updated"] for row in templates}) == 1
    assert all(row["created_at"] == row["last_updated"] for row in templates)


def test_synchronous_ingestion_shares_creation_and_update_across_chunks():
    sb, table = _database([])
    with (
        patch.object(ingestion, "get_supabase", return_value=sb),
        patch.object(ingestion, "check_duplicate", return_value=False),
        patch("services.parser.parse_document", return_value="body"),
        patch("services.chunker.chunk_text", return_value=["one", "two"]),
        patch("services.contextual.contextualize_chunks", return_value=["", ""]),
        patch("services.embeddings.embed_batch", return_value=[[0.1], [0.2]]),
    ):
        ingestion.ingest_document(b"file", "api.md", "u1")
    rows = [call.args[0] for call in table.insert.call_args_list]
    assert len(rows) == 2
    assert len({row["last_updated"] for row in rows}) == 1
    assert all(row["created_at"] == row["last_updated"] for row in rows)


@pytest.mark.parametrize("fast_mode", [True, False])
def test_freshness_is_applied_after_rerank_in_both_retrieval_paths(fast_mode):
    from services import search

    now = datetime.now(timezone.utc)
    old = {
        "id": "old",
        "content": "API spec",
        "source_type": "pdf",
        "metadata": {},
        "last_updated": (now - timedelta(days=365)).isoformat(),
        "rerank_score": 0.8,
    }
    fresh = {**old, "id": "fresh", "last_updated": now.isoformat(), "rerank_score": 0.79}
    with (
        patch.object(search, "_vector_search", return_value=[old, fresh]),
        patch.object(search, "_keyword_search", return_value=[]),
        patch.object(search, "rerank", return_value=[old, fresh]) as rerank,
        patch.object(search, "rewrite_query", return_value="API"),
        patch.object(search, "generate_multi_queries", return_value=[]),
        patch.object(search, "_expand_with_neighbors", side_effect=lambda rows: rows) as expand,
    ):
        result = search.search_documents(
            [], "API", user_id="u1", fast_mode=fast_mode, include_code=False
        )
    assert [row["id"] for row in rerank.return_value] == ["old", "fresh"]
    assert [row["id"] for row in result] == ["fresh", "old"]
    assert expand.call_args.args[0] == result


@pytest.mark.asyncio
async def test_mcp_search_exposes_creation_and_last_update(monkeypatch):
    import mcp_server
    from services.retrieval import UnifiedHit

    user_token = mcp_server._current_user_id.set("u1")
    monkeypatch.setattr(mcp_server, "get_supabase", MagicMock())
    monkeypatch.setattr(mcp_server, "embed_query", lambda _: [])
    monkeypatch.setattr(
        mcp_server,
        "retrieve_knowledge",
        AsyncMock(
            return_value=SimpleNamespace(
                hits=[
                    UnifiedHit(
                        "docs",
                        "d1",
                        "API specification",
                        metadata={
                            "source_filename": "api.pdf",
                            "created_at": "2025-01-01",
                            "last_updated": "2026-10-23",
                        },
                    ),
                ]
            )
        ),
    )
    try:
        result = await mcp_server.knowledge_base_search("API")
    finally:
        mcp_server._current_user_id.reset(user_token)
    assert "api.pdf — 2025-01-01 — last updated 2026-10-23" in result
