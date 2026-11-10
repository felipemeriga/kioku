"""Authenticated protocol probes, without CLI credentials, LLMs or SDK internals."""

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from threading import Barrier
from unittest.mock import patch

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from mcp.server.fastmcp import FastMCP
from mcp.types import TextContent

from services.ai import native_tools


def frame(response):
    assert response.status_code == 200, response.text
    return json.loads(
        next(line[6:] for line in response.text.splitlines() if line.startswith("data: "))
    )


def client_fixture(server, monkeypatch):
    key = "isolated-fixture-key-with-at-least-thirty-two-bytes"
    monkeypatch.setenv("TSUKAI_CAPABILITY_KEY", key)
    grant = {
        "iss": "kioku-backend",
        "aud": "kioku-native-tools",
        "iat": int(time.time()),
        "exp": int(time.time()) + 60,
        "jti": "fixture",
        "owner_id": "owner",
        "job_id": "job",
        "attempt_id": "attempt",
        "folder_ids": ["folder"],
        "tool_allowlist": ["knowledge_base_search"],
    }

    @asynccontextmanager
    async def lifespan(_app):
        async with server.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount("/mcp", native_tools.NativeToolAuth(server.streamable_http_app()))
    headers = {
        "Authorization": "Bearer " + jwt.encode(grant, key, algorithm="HS256"),
        "Accept": "application/json, text/event-stream",
    }
    turn = {
        "id": "turn",
        "conversation_id": "conversation",
        "request": {
            "operation": "rag_agent",
            "metadata": {"intent": {"scope_filename": None}},
        },
    }
    return app, headers, turn, grant


def rpc(client, headers, method, params=None):
    return client.post(
        "/mcp/",
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        },
    )


def initialize(client, headers):
    return frame(
        rpc(
            client,
            headers,
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "no-model-probe", "version": "1"},
            },
        )
    )["result"]


def test_tools_only_capabilities_keep_all_seven_tools_and_auth(monkeypatch):
    observed = []

    def runner(name, arguments):
        observed.append((name, arguments, native_tools._authority.get()["owner_id"]))
        return "fixture evidence"

    server = native_tools.create_native_mcp(runner=runner)
    baseline = native_tools.create_native_mcp(
        server=FastMCP("Kioku", host="0.0.0.0", stateless_http=True, streamable_http_path="/"),
        runner=runner,
    )
    assert [tool.model_dump() for tool in asyncio.run(server.list_tools())] == [
        tool.model_dump() for tool in asyncio.run(baseline.list_tools())
    ]
    app, headers, turn, grant = client_fixture(server, monkeypatch)
    with (
        patch.object(native_tools, "owned_turn", return_value=turn),
        patch.object(native_tools, "verify_attempt", return_value=grant) as verify,
        TestClient(app) as client,
    ):
        caps = initialize(client, headers)["capabilities"]
        assert "tools" in caps
        assert not {"resources", "prompts", "logging", "completions"}.intersection(caps)
        tools = frame(rpc(client, headers, "tools/list"))["result"]["tools"]
        assert len(tools) == 7
        names = {tool["name"] for tool in tools}
        assert {"search_agent_history", "read_agent_evidence", "knowledge_base_search"} <= names
        result = frame(
            rpc(
                client,
                headers,
                "tools/call",
                {
                    "name": "knowledge_base_search",
                    "arguments": {"query": "test"},
                },
            )
        )["result"]
        assert result["content"][0]["text"] == "fixture evidence"
        assert observed[0][0] == "knowledge_base_search" and observed[0][2] == "owner"
        invalid = frame(
            rpc(
                client,
                headers,
                "tools/call",
                {
                    "name": "search_agent_history",
                    "arguments": {"limit": 1000},
                },
            )
        )["result"]
        assert invalid["isError"]
        assert len(observed) == 1
        assert verify.call_count == 4  # Metadata requests retain the same live authority checks.
        assert client.post("/mcp/", json={}).status_code == 401
        verify.side_effect = HTTPException(403, "Inactive native tool attempt")
        assert rpc(client, headers, "initialize").status_code == 403
    assert native_tools._authority.get() is None


def test_domain_reads_advertise_parallel_safe_annotations_on_wire(monkeypatch):
    server = native_tools.create_native_mcp(runner=lambda _name, _arguments: "fixture")
    app, headers, turn, grant = client_fixture(server, monkeypatch)
    with (
        patch.object(native_tools, "owned_turn", return_value=turn),
        patch.object(native_tools, "verify_attempt", return_value=grant),
        TestClient(app) as client,
    ):
        tools = frame(rpc(client, headers, "tools/list"))["result"]["tools"]
    reads = {
        "knowledge_base_search",
        "code_graph_lookup",
        "recent_changes",
        "search_agent_history",
        "read_agent_evidence",
    }
    assert {tool["name"] for tool in tools} == reads | {
        "query_documents_metadata",
        "web_search",
    }
    for tool in tools:
        if tool["name"] in reads:
            assert tool["annotations"]["readOnlyHint"] is True
            assert tool["annotations"]["destructiveHint"] is False
            assert tool["annotations"]["openWorldHint"] is False
        else:
            assert tool.get("annotations") is None


def test_authenticated_independent_read_calls_can_overlap(monkeypatch):
    entered = Barrier(2)

    def runner(_name, arguments):
        authority = native_tools._authority.get()
        owner = authority["owner_id"]
        folders = ",".join(authority["folder_ids"])
        entered.wait(timeout=5)
        return owner + ":" + folders + ":" + arguments["query"]

    server = native_tools.create_native_mcp(runner=runner)
    app, headers, turn, grant = client_fixture(server, monkeypatch)
    other_grant = {**grant, "owner_id": "other-owner", "folder_ids": ["other-folder"]}
    other_headers = {
        **headers,
        "Authorization": "Bearer "
        + jwt.encode(
            other_grant, "isolated-fixture-key-with-at-least-thirty-two-bytes", algorithm="HS256"
        ),
    }

    def owned(owner, *, job_id, authority_only=False):
        assert authority_only is True
        return {**turn, "owner": owner}

    def verified(owned_turn, _attempt):
        return other_grant if owned_turn["owner"] == "other-owner" else grant

    with (
        patch.object(native_tools, "owned_turn", side_effect=owned),
        patch.object(native_tools, "verify_attempt", side_effect=verified) as verify,
        TestClient(app) as client,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):

        def invoke(item):
            query, request_headers = item
            return frame(
                rpc(
                    client,
                    request_headers,
                    "tools/call",
                    {"name": "knowledge_base_search", "arguments": {"query": query}},
                )
            )["result"]

        results = list(pool.map(invoke, [("first", headers), ("second", other_headers)]))
        assert [result["content"][0]["text"] for result in results] == [
            "owner:folder:first",
            "other-owner:other-folder:second",
        ]
        assert verify.call_count == 2
    assert native_tools._authority.get() is None


@pytest.mark.parametrize("kind", ["text", "dictionary", "unstructured", "error"])
def test_public_adapter_preserves_fastmcp_wire_results(monkeypatch, kind):
    def text(query: str) -> str:
        return query

    def dictionary(query: str) -> dict[str, str]:
        return {"value": query}

    def unstructured(query: str) -> list[TextContent]:
        return [TextContent(type="text", text=query)]

    def error(query: str) -> str:
        raise ValueError("fixture failure")

    responses = []
    for tools_only in (False, True):
        registry = FastMCP("Fixture", host="0.0.0.0", stateless_http=True, streamable_http_path="/")
        function = {
            "text": text,
            "dictionary": dictionary,
            "unstructured": unstructured,
            "error": error,
        }[kind]
        registry.add_tool(function, structured_output=kind != "unstructured")
        server = native_tools.ToolsOnlyMCP(registry) if tools_only else registry
        app, headers, turn, grant = client_fixture(server, monkeypatch)
        with (
            patch.object(native_tools, "owned_turn", return_value=turn),
            patch.object(native_tools, "verify_attempt", return_value=grant),
            TestClient(app) as client,
        ):
            initialize(client, headers)
            listed = frame(rpc(client, headers, "tools/list"))["result"]["tools"]
            result = frame(
                rpc(
                    client,
                    headers,
                    "tools/call",
                    {
                        "name": kind,
                        "arguments": {"query": "fixture"},
                    },
                )
            )["result"]
            responses.append((listed, result))
    assert responses[0] == responses[1]


def test_capability_aware_probe_avoids_only_empty_metadata_families(monkeypatch):
    methods = []
    for tools_only in (False, True):
        registry = FastMCP("Fixture", host="0.0.0.0", stateless_http=True, streamable_http_path="/")
        server = native_tools.ToolsOnlyMCP(registry) if tools_only else registry
        app, headers, turn, grant = client_fixture(server, monkeypatch)
        calls = []
        with (
            patch.object(native_tools, "owned_turn", return_value=turn),
            patch.object(native_tools, "verify_attempt", return_value=grant),
            TestClient(app) as client,
        ):
            caps = initialize(client, headers)["capabilities"]
            calls.append("initialize")
            for capability, names in (
                ("tools", ["tools/list"]),
                ("resources", ["resources/list", "resources/templates/list"]),
                ("prompts", ["prompts/list"]),
            ):
                if capability in caps:
                    for name in names:
                        frame(rpc(client, headers, name))
                        calls.append(name)
        methods.append(calls)
    assert methods == [
        ["initialize", "tools/list", "resources/list", "resources/templates/list", "prompts/list"],
        ["initialize", "tools/list"],
    ]
