"""Real ingestion contextual workers retain the authenticated document owner."""

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.ai.client import ExecutionResult
from services.ai.scope import current_scope
from services.ingestion import ingest_document, replace_document
from services.queue.tasks import ingest_document_task


@pytest.fixture
def providers(monkeypatch):
    monkeypatch.setenv("TSUKAI_NATIVE_TASKS", "contextual")
    monkeypatch.setenv("TSUKAI_CREDENTIAL_OWNER_ID", "owner")
    native, api = MagicMock(), MagicMock()
    native.complete.return_value = ExecutionResult(
        "job",
        "",
        {
            "schema_version": 1,
            "outcome": "completed",
            "data": {"text": "context"},
            "missing_inputs": [],
            "failure": None,
            "warnings": [],
        },
        None,
        "session",
    )
    api.messages.create.return_value = SimpleNamespace(content=[SimpleNamespace(text="context")])
    with ExitStack() as stack:
        factory = stack.enter_context(patch("services.ai.facade.client_for", return_value=native))
        stack.enter_context(patch("services.ai.facade.consume_result"))
        stack.enter_context(patch("services.llm.get_client", return_value=api))
        yield native, api, factory


def assert_routing(providers, owner):
    native, api, factory = providers
    assert native.complete.call_count == (2 if owner == "owner" else 0)
    assert api.messages.create.call_count == (0 if owner == "owner" else 2)
    for call in factory.call_args_list:
        scope = call.args[0]
        assert scope.owner_id == owner and scope.folder_ids == ("folder",)
    assert current_scope() is None


@pytest.mark.parametrize("owner", ["owner", "another-user"])
@pytest.mark.parametrize("operation", ["ingest", "replace"])
def test_synchronous_document_scope_reaches_contextual_workers(providers, owner, operation):
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "document"}]
    existing = sb.table.return_value.select.return_value
    existing = existing.eq.return_value.eq.return_value.eq.return_value
    existing.order.return_value.execute.return_value.data = []
    with (
        patch("services.ingestion.get_supabase", return_value=sb),
        patch("services.ingestion.check_duplicate", return_value=False),
        patch("services.scope.resolve_root_folder_id", return_value="folder"),
        patch("services.parser.parse_document", return_value="source " * 200),
        patch("services.chunker.chunk_text", return_value=["first", "second"]),
        patch("services.embeddings.embed_batch", return_value=[[0.1], [0.2]]),
    ):
        result = (
            ingest_document(b"file", "guide.md", owner, "folder")
            if operation == "ingest"
            else replace_document("source " * 200, "guide.md", owner, "folder")
        )
    assert result["chunks"] == 2
    assert_routing(providers, owner)


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", ["owner", "another-user"])
async def test_upload_scope_crosses_async_and_contextual_threadpools(providers, owner):
    sb, redis = MagicMock(), SimpleNamespace(enqueue_job=AsyncMock())
    sb.storage.from_.return_value.download.return_value = b"file"
    with (
        patch("services.queue.tasks.get_supabase_thread_safe", return_value=sb),
        patch("services.queue.tasks.mark_running"),
        patch("services.queue.tasks.mark_failed") as failed,
        patch("services.queue.tasks.set_total_batches"),
        patch("services.queue.tasks.chunk_text", return_value=["first", "second"]),
        patch("services.parser.parse_document", return_value="source " * 200),
    ):
        await ingest_document_task(
            {"redis": redis},
            {
                "job_id": "job",
                "user_id": owner,
                "folder_id": "folder",
                "filename": "guide.md",
                "storage_bucket": "documents",
                "storage_path": "file",
                "media_kind": "document",
                "source_type": "markdown",
                "content_hash": "hash",
            },
        )
    failed.assert_not_called()
    assert redis.enqueue_job.await_args.args[1]["contexts"] == ["context", "context"]
    assert_routing(providers, owner)


def test_document_scope_narrows_without_changing_mcp_identity_or_nested_authority():
    from services.ai.scope import ExecutionScope, document_scope, execution_scope

    with execution_scope(ExecutionScope("owner", ("folder", "sibling"), caller="mcp")):
        narrowed = document_scope("owner", "folder")
        assert narrowed.caller == "mcp" and narrowed.folder_ids == ("folder",)
        with pytest.raises(PermissionError):
            document_scope("another-user", "folder")
        with pytest.raises(PermissionError):
            document_scope("owner", "outside")
    with execution_scope(ExecutionScope("owner", ("folder",), harness_tool=True)):
        assert document_scope("owner", "folder").harness_tool is True
