from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.ai import native_tools


def test_actual_streamable_mcp_lifespan_initialize_list_call_and_scope_context():
    server = native_tools.create_native_mcp()

    @asynccontextmanager
    async def lifespan(app):
        async with server.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount("/internal/tsukai/mcp", native_tools.NativeToolAuth(server.streamable_http_app()))
    authority = {
        "owner_id": "owner",
        "folder_ids": ["folder"],
        "tool_allowlist": ["knowledge_base_search"],
        "job_id": "job",
        "attempt_id": "attempt",
    }
    observed = []

    def run(name, args):
        observed.append((name, args, native_tools._authority.get()))
        return "Real Kioku evidence fixture: retry limit 3"

    headers = {"Authorization": "Bearer fixture", "Accept": "application/json, text/event-stream"}
    with patch.object(native_tools, "authenticate_tool", return_value=authority):
        with patch.object(native_tools, "run_tool", side_effect=run):
            with TestClient(app) as client:
                response = client.post(
                    "/internal/tsukai/mcp/",
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {"name": "test-native", "version": "1"},
                        },
                    },
                )
                assert response.status_code == 200
                response = client.post(
                    "/internal/tsukai/mcp/",
                    headers=headers,
                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                )
                assert response.status_code == 200
                assert "knowledge_base_search" in response.text
                response = client.post(
                    "/internal/tsukai/mcp/",
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {
                            "name": "knowledge_base_search",
                            "arguments": {"query": "retry"},
                        },
                    },
                )
                assert response.status_code == 200
                assert "retry limit 3" in response.text
    assert observed[0][0] == "knowledge_base_search"
    assert observed[0][2]["owner_id"] == "owner"
    assert native_tools._authority.get() is None


def test_tool_trace_keeps_exact_result_and_bounded_preview():
    grant = {
        "owner_id": "owner",
        "folder_ids": ["folder"],
        "job_id": "job",
        "attempt_id": "attempt",
        "turn_id": "turn",
        "operation": "rag_agent",
        "tool_allowlist": ["knowledge_base_search"],
    }
    client = MagicMock()
    exact = "x" * 5000

    def execute(*args, **kwargs):
        assert kwargs["fast_mode"] is True
        assert kwargs["full_debug"] is True
        kwargs["debug_retrieval"].append({"content": exact, "folder_id": "folder"})
        return exact

    token = native_tools._authority.set(grant)
    try:
        with (
            patch.object(native_tools, "client_for", return_value=client),
            patch.object(native_tools, "execute_tool", side_effect=execute),
            patch.object(native_tools, "scope_locations", return_value={"folder_ids": ["folder"]}),
            patch.object(native_tools, "save_trace", return_value="artifact") as saved,
        ):
            result = native_tools.run_tool("knowledge_base_search", {"query": "retry"})
        assert result == exact
        assert saved.call_args.args[-1] == exact
        completed = client.tool_events.call_args.args[-1]
        assert [kind for kind, data in completed] == ["retrieval.completed", "tool.completed"]
        preview = completed[-1][1]
        assert len(preview["sources"][0]["content"]) == 1200
        assert preview["result_ref"] == "artifact"
        assert preview["effective_scope"]["folder_ids"] == ["folder"]
    finally:
        native_tools._authority.reset(token)


def test_mounted_mcp_slow_tool_does_not_block_health():
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor

    # Build a fresh server to avoid reusing its one-shot session manager across lifespans.
    from mcp.server.fastmcp import FastMCP

    server = FastMCP(
        "Responsiveness", host="0.0.0.0", stateless_http=True, streamable_http_path="/"
    )
    entered, release = threading.Event(), threading.Event()

    def slow(*args):
        entered.set()
        release.wait(2)
        return "bounded result"

    @server.tool()
    async def knowledge_base_search(query: str) -> str:
        # The production registration must itself remain async, not SDK sync execution.
        return await native_tools.knowledge_base_search(query)

    @asynccontextmanager
    async def lifespan(app):
        async with server.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount("/mcp", server.streamable_http_app())

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    with patch.object(native_tools, "run_tool", side_effect=slow):
        with TestClient(app) as client, ThreadPoolExecutor(1) as pool:
            pending = pool.submit(
                client.post,
                "/mcp/",
                headers={"Accept": "application/json, text/event-stream"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "knowledge_base_search", "arguments": {"query": "slow"}},
                },
            )
            try:
                assert entered.wait(1)
                start = time.monotonic()
                assert client.get("/health").status_code == 200
                assert time.monotonic() - start < 0.5
                assert not pending.done()
            finally:
                release.set()
            assert pending.result().status_code == 200


def test_metadata_child_is_consumed_only_after_root_tool_artifact_commits():
    grant = {
        "owner_id": "owner",
        "folder_ids": ["folder"],
        "job_id": "parent",
        "attempt_id": "attempt",
        "turn_id": "turn",
        "operation": "rag_agent",
        "tool_allowlist": ["query_documents_metadata"],
    }
    order = []
    client = MagicMock()

    def metadata(question, authority, *, on_consumption):
        on_consumption({"job_id": "child"})
        return '{"count":3}'

    def saved(*args):
        order.append("artifact")
        return "durable-artifact"

    token = native_tools._authority.set(grant)
    try:
        with (
            patch.object(native_tools, "client_for", return_value=client),
            patch.object(native_tools, "scope_locations", return_value={"folder_ids": ["folder"]}),
            patch.object(native_tools, "save_trace", side_effect=saved),
            patch("services.ai.metadata.metadata_query", side_effect=metadata),
            patch(
                "services.ai.metadata.consume_metadata",
                side_effect=lambda receipt, artifact: order.append("consume"),
            ),
        ):
            assert (
                native_tools.run_tool("query_documents_metadata", {"question": "count"})
                == '{"count":3}'
            )
        assert order == ["artifact", "consume"]
    finally:
        native_tools._authority.reset(token)
