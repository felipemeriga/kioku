"""The temporary evaluation service must retain fixed owner and folder authority."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient


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
        assert (
            client.post(
                "/prepare",
                headers=headers,
                json={"case": "owned", "question": "How does it work?", "folder_ids": ["folder"]},
            ).status_code
            == 200
        )
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
