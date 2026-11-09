"""The temporary evaluation service must retain fixed owner and folder authority."""

import asyncio
import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from services.ai import native_tools
from services.ai.chat import NATIVE_CHAT_PROMPT, native_chat_prompt


def test_wrong_retrieval_source_is_rejected_before_server_start():
    path = Path(__file__).resolve().parents[2] / "scripts/benchmarks/shadow_tools.py"
    spec = importlib.util.spec_from_file_location("shadow_wrong_source", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError, match="expected candidate source"):
        module.application(
            {
                "owner_id": "owner",
                "folder_ids": ["folder"],
                "token": "t" * 40,
                "remote": "/unrelated-candidate",
            }
        )


def test_shadow_service_requires_token_and_cannot_expand_case_scope(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "scripts/benchmarks/shadow_tools.py"
    spec = importlib.util.spec_from_file_location("shadow_evaluation", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    config = {"owner_id": "owner", "folder_ids": ["folder"], "token": "t" * 40}
    db = MagicMock()
    query = db.table.return_value.select.return_value.eq.return_value.in_.return_value
    query.execute.return_value.data = [{"id": "folder", "name": "repo"}]
    monkeypatch.setattr(module, "get_supabase_thread_safe", lambda: db)
    calls = []

    def execute(name, args, owner, **kwargs):
        calls.append((name, args, owner, kwargs))
        return "Scoped evidence [1]"

    monkeypatch.setattr(module, "execute_tool", execute)
    headers = {"Authorization": "Bearer " + config["token"]}
    with TestClient(module.application(config), base_url="http://localhost") as client:
        assert client.get("/result/private").status_code == 401
        assert (
            client.post(
                "/prepare",
                headers=headers,
                json={"case": "forbidden", "question": "Find it", "folder_ids": ["foreign"]},
            ).status_code
            == 403
        )
        response = client.post(
            "/prepare",
            headers=headers,
            json={"case": "owned", "question": "How does it work?", "folder_ids": ["folder"]},
        )
        assert response.status_code == 200
        contract = response.json()["chat_contract"]
        assert contract["system_prompt"] == NATIVE_CHAT_PROMPT
        prompt = json.loads(contract["prompt"])
        assert contract["prompt"] == native_chat_prompt(
            content="How does it work?",
            history=[],
            turn_id="owned",
            time_context=prompt["time_context"],
            evidence=response.json()["evidence"],
        )
        assert contract["max_tokens"] == 6000 and contract["max_turns"] == 8
        assert calls[0][2] == "owner"
        assert calls[0][3]["scope_folder_ids"] == ["folder"]
        mcp_headers = {
            **headers,
            "Accept": "application/json, text/event-stream",
            "X-Kioku-Benchmark-Case": "owned",
        }
        response = client.post(
            "/mcp/",
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "knowledge_base_search", "arguments": {"query": "specific"}},
            },
        )
        assert response.status_code == 200
        assert "Scoped evidence" in response.text
        assert set(calls[-1][1]) == {"query", "created_after", "created_before"}
        assert calls[-1][1]["query"] == "specific"
        assert client.get("/result/owned", headers=headers).status_code == 200
        response = client.post(
            "/mcp/",
            headers=mcp_headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert response.status_code == 200
        assert "earlier pages can miss later follow-ups" in response.text
        before_unsupported = len(calls)
        unsupported = client.post(
            "/mcp/",
            headers=mcp_headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "query_documents_metadata",
                    "arguments": {"question": "Count documents"},
                },
            },
        )
        assert unsupported.status_code == 200
        assert len(calls) == before_unsupported
        result = client.get("/result/owned", headers=headers).json()
        assert result["unsupported_calls"] == ["query_documents_metadata"]
        before = len(calls)
        response = client.post(
            "/prepare",
            headers=headers,
            json={
                "case": "agent-plans",
                "question": "What did we try?",
                "folder_ids": ["folder"],
                "skip_prefetch": True,
            },
        )
        assert response.status_code == 200
        assert len(calls) == before
        assert "not_prefetched" in response.json()["evidence"]


def test_shadow_mcp_exposes_identical_production_tool_contract():
    production = native_tools.create_native_mcp()
    evaluation = native_tools.create_native_mcp(runner=lambda name, args: "fixture")

    async def schemas(server):
        return [tool.model_dump() for tool in await server.list_tools()]

    assert asyncio.run(schemas(production)) == asyncio.run(schemas(evaluation))
