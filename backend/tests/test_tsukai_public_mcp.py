"""The external MCP service remains responsive during direct generative waits."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi.testclient import TestClient


def test_public_mcp_model_wait_does_not_block_other_tools():
    import mcp_server

    entered, release = threading.Event(), threading.Event()

    def slow_metadata(*args):
        entered.set()
        release.wait(2)
        return '{"operation":"scoped_count","data":{"count":3}}'

    headers = {"Authorization": "Bearer fixture", "Accept": "application/json, text/event-stream"}
    with (
        patch.object(mcp_server, "_verify_api_key", return_value=("owner", "folder")),
        patch.object(mcp_server, "_descendant_folder_ids", return_value=["folder"]),
        patch.object(mcp_server, "get_supabase"),
        patch("services.ai.registry.engine_for", return_value="tsukai"),
        patch("services.ai.metadata.metadata_query", side_effect=slow_metadata),
    ):
        with TestClient(mcp_server.build_app()) as client, ThreadPoolExecutor(1) as pool:
            initialized = client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "public-test", "version": "1"},
                    },
                },
            )
            assert initialized.status_code == 200
            headers["Mcp-Session-Id"] = initialized.headers["Mcp-Session-Id"]
            pending = pool.submit(
                client.post,
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "query_documents_metadata",
                        "arguments": {"question": "count files"},
                    },
                },
            )
            try:
                assert entered.wait(1)
                started = time.monotonic()
                other = client.post(
                    "/mcp",
                    headers=headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "get_folder_briefing_schema", "arguments": {}},
                    },
                )
                assert other.status_code == 200
                assert "overview" in other.text
                assert time.monotonic() - started < 0.5
                assert not pending.done()
            finally:
                release.set()
            assert "scoped_count" in pending.result().text
