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
        patch.object(
            mcp_server,
            "_verify_api_key",
            side_effect=lambda key: (
                ("owner", "folder") if key == "fixture" else ("foreign", "foreign-folder")
            ),
        ),
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
            foreign_headers = {**headers, "Authorization": "Bearer foreign-key"}
            foreign = client.post(
                "/mcp",
                headers=foreign_headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 99,
                    "method": "tools/call",
                    "params": {
                        "name": "query_documents_metadata",
                        "arguments": {"question": "steal scope"},
                    },
                },
            )
            assert foreign.status_code == 403
            assert not entered.is_set()
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


def test_api_key_scope_is_rechecked_against_current_folder_owner():
    from unittest.mock import MagicMock

    import mcp_server

    sb = MagicMock()
    keys, folders = MagicMock(), MagicMock()
    sb.table.side_effect = lambda name: keys if name == "api_keys" else folders
    keys.select.return_value.eq.return_value.execute.return_value.data = [
        {"user_id": "owner", "scope_folder_id": "now-foreign-folder"}
    ]
    scoped = folders.select.return_value.eq.return_value.eq.return_value.limit.return_value
    scoped.execute.return_value.data = []
    with patch.object(mcp_server, "get_supabase", return_value=sb):
        assert mcp_server._verify_api_key("fixture-key") is None
