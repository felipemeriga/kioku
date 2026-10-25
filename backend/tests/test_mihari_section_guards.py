import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from main import app
from routes import mihari


def _authorize(monkeypatch):
    monkeypatch.setattr(mihari, "_api_key_auth", lambda _request: ("u1", "f1", "rag_test"))
    monkeypatch.setattr(mihari, "get_supabase", lambda: object())
    monkeypatch.setattr("mcp_server._descendant_folder_ids", lambda *_: ["f1"])


def test_activity_does_not_call_model_for_pinned_section(monkeypatch):
    _authorize(monkeypatch)
    monkeypatch.setattr(
        "services.folder_summary.repo.get_latest_summary",
        lambda *_: {"content": {"sections": {"activity": {"status": "pinned", "content": {}}}}},
    )
    monkeypatch.setattr(
        "services.llm.complete", lambda **_kwargs: (_ for _ in ()).throw(AssertionError())
    )
    response = TestClient(app).post(
        "/api/mihari/activity",
        json={"folder_id": "f1", "head_sha": "abc", "commits": [{"sha": "abc", "subject": "Fix"}]},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "updated": False, "reason": "section edited by user"}


def test_section_does_not_call_model_for_hybrid_section(monkeypatch):
    _authorize(monkeypatch)
    monkeypatch.setattr(
        "services.folder_summary.repo.get_latest_summary",
        lambda *_: {
            "content": {"sections": {"how_it_runs": {"status": "hybrid", "content": "Run it"}}}
        },
    )
    monkeypatch.setattr(
        "services.llm.complete", lambda **_kwargs: (_ for _ in ()).throw(AssertionError())
    )
    response = TestClient(app).post(
        "/api/mihari/section",
        json={
            "folder_id": "f1",
            "section": "how_it_runs",
            "files": [{"path": "README.md", "content": "Run it"}],
        },
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "updated": False, "reason": "section edited by user"}


def test_reground_preserves_pinned_overview(monkeypatch):
    writes = []

    class Query:
        def select(self, *_args):
            return self

        def eq(self, *_args):
            return self

        def limit(self, *_args):
            return self

        def execute(self):
            return SimpleNamespace(data=[])

    class DB:
        def table(self, _name):
            return Query()

        def rpc(self, _name, payload):
            writes.append(payload)
            return Query()

    monkeypatch.setattr(mihari, "_api_key_auth", lambda _request: ("u1", "f1", "rag_test"))
    monkeypatch.setattr(mihari, "get_supabase", lambda: DB())
    monkeypatch.setattr("mcp_server._descendant_folder_ids", lambda *_: ["f1"])
    monkeypatch.setattr(
        "services.folder_summary.repo.get_latest_summary",
        lambda *_: {
            "content": {
                "sections": {
                    "overview": {"status": "pinned", "content": {"purpose": "Human"}},
                    "architecture": {"status": "auto", "content": {"summary": "Old"}},
                }
            }
        },
    )
    data = {
        "overview": {"purpose": "Model", "description": "Generated"},
        "architecture": {
            "summary": "The API handles requests.",
            "components": [{"name": "API", "role": "Handles requests", "path": "main.py"}],
            "data_flow": "Requests enter main.py.",
        },
    }
    monkeypatch.setattr(
        "services.llm.complete",
        lambda **_kwargs: SimpleNamespace(content=[SimpleNamespace(text=json.dumps(data))]),
    )
    response = TestClient(app).post(
        "/api/mihari/reground",
        json={"folder_id": "f1", "files": [{"path": "main.py", "content": "def app(): pass"}]},
    )
    assert response.status_code == 200
    assert response.json()["sections"] == ["architecture"]
    assert [write["p_section"] for write in writes] == ["architecture"]
