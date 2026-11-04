import json
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
from anthropic import BadRequestError
from fastapi.testclient import TestClient

from main import app
from routes import mihari


def test_legacy_force_init_pin_is_watcher_writable():
    assert not mihari._user_edited({"status": "pinned", "provenance": "agent_mcp"})
    assert mihari._user_edited({"status": "pinned", "provenance": "user_ui"})


class Query:
    def __init__(self, data, writes=None):
        self.data = data
        self.writes = writes

    def select(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args):
        return self

    def execute(self):
        return SimpleNamespace(data=self.data)

    def insert(self, payload):
        if self.writes is not None:
            self.writes.append(payload)
        return self

    def upsert(self, payload, **_kwargs):
        self.writes.append(payload)
        return self


class DB:
    def __init__(self):
        self.writes = []

    def table(self, name):
        if name == "repo_documentation":
            return Query([{"abstract": "API and worker architecture"}])
        if name == "repo_freshness":
            return Query(
                [{"section_reviews": {"activity": {"reviewed_at": "old", "head_sha": "a" * 40}}}],
                self.writes,
            )
        if name == "maintenance_preparations":
            return Query([], self.writes)
        raise AssertionError(name)

    def rpc(self, name, payload):
        assert name == "apply_maintenance_result"
        value = payload["p_value"]
        if "selected" in value:
            return Query(
                {
                    "ok": True,
                    "selected": value["selected"],
                    "reviewed": ["architecture", "overview", "documentation"],
                }
            )
        return Query({"ok": True, "updated": False, "reason": "content unchanged"})


def test_review_plan_can_choose_activity_only_and_still_review_full_briefing(monkeypatch):
    db = DB()
    monkeypatch.setattr(mihari, "_api_key_auth", lambda _request: ("u1", "f1", "rag_test"))
    monkeypatch.setattr(mihari, "get_supabase", lambda: db)
    monkeypatch.setattr("mcp_server._descendant_folder_ids", lambda *_: ["f1"])
    monkeypatch.setattr(
        "services.folder_summary.repo.get_latest_summary",
        lambda *_: {
            "content": {
                "sections": {
                    "architecture": {"content": {"summary": "API and worker"}},
                    "overview": {"content": {"purpose": "Repository memory"}},
                    "documentation": {"content": "Detailed docs available"},
                }
            }
        },
    )
    monkeypatch.setattr(
        "services.llm.complete",
        lambda **_kwargs: SimpleNamespace(
            content=[SimpleNamespace(text=json.dumps({"selected": ["activity"]}))]
        ),
    )
    response = TestClient(app).post(
        "/api/mihari/review-plan",
        json={
            "folder_id": "f1",
            "head_sha": "a" * 40,
            "changed_paths": ["backend/services/search.py"],
            "commits": ["Improve retrieval latency"],
            "patch": "Optimize reranker call",
        },
    )
    assert response.status_code == 200
    assert response.json()["selected"] == ["activity"]
    assert set(response.json()["reviewed"]) == {"architecture", "overview", "documentation"}


def test_review_plan_rejects_invalid_model_reply_without_expensive_fallback(monkeypatch):
    db = DB()
    monkeypatch.setattr(mihari, "_api_key_auth", lambda _request: ("u1", "f1", "rag_test"))
    monkeypatch.setattr(mihari, "get_supabase", lambda: db)
    monkeypatch.setattr("mcp_server._descendant_folder_ids", lambda *_: ["f1"])
    monkeypatch.setattr(
        "services.folder_summary.repo.get_latest_summary",
        lambda *_: {"content": {"sections": {"overview": {"content": "Repository memory"}}}},
    )
    monkeypatch.setattr(
        "services.llm.complete",
        lambda **_kwargs: SimpleNamespace(content=[SimpleNamespace(text="Not valid JSON")]),
    )
    response = TestClient(app).post(
        "/api/mihari/review-plan",
        json={"folder_id": "f1", "head_sha": "a" * 40},
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "invalid briefing review plan"


def test_review_plan_reports_exhausted_anthropic_credits(monkeypatch):
    db = DB()
    monkeypatch.setattr(mihari, "_api_key_auth", lambda _request: ("u1", "f1", "rag_test"))
    monkeypatch.setattr(mihari, "get_supabase", lambda: db)
    monkeypatch.setattr("mcp_server._descendant_folder_ids", lambda *_: ["f1"])
    monkeypatch.setattr(
        "services.folder_summary.repo.get_latest_summary",
        lambda *_: {"content": {"sections": {"overview": {"content": "Repository memory"}}}},
    )

    def exhausted(**_kwargs):
        response = httpx.Response(
            400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        )
        raise BadRequestError(
            "Your credit balance is too low to access the Anthropic API.",
            response=response,
            body={"error": {"type": "invalid_request_error"}},
        )

    monkeypatch.setattr("services.llm.complete", exhausted)
    response = TestClient(app).post(
        "/api/mihari/review-plan",
        json={"folder_id": "f1", "head_sha": "a" * 40},
    )
    assert response.status_code == 503
    assert "credits exhausted" in response.json()["detail"]


def test_review_completion_preserves_other_markers(monkeypatch):
    db = DB()
    monkeypatch.setattr(mihari, "_api_key_auth", lambda _request: ("u1", "f1", "rag_test"))
    monkeypatch.setattr(mihari, "get_supabase", lambda: db)
    monkeypatch.setattr("mcp_server._descendant_folder_ids", lambda *_: ["f1"])
    response = TestClient(app).post(
        "/api/mihari/review-complete",
        json={
            "folder_id": "f1",
            "head_sha": "b" * 40,
            "reviewed": ["architecture", "overview", "documentation"],
        },
    )
    assert response.status_code == 200
    assert db.writes[0]["section_reviews"]["activity"]["head_sha"] == "a" * 40
    assert db.writes[0]["section_reviews"]["documentation"]["head_sha"] == "b" * 40
    assert "checked_at" not in db.writes[0]


def test_documentation_refresh_collects_streamed_response(monkeypatch):
    guide = "Repository architecture and operations. " * 25
    abstract = "API and worker architecture"

    class DocumentationDB:
        def table(self, name):
            if name == "repo_documentation":
                return Query([{"content": guide, "abstract": abstract}])
            if name in ("repo_freshness", "maintenance_preparations"):
                return Query([])
            raise AssertionError(name)

        def rpc(self, name, payload):
            assert name == "apply_maintenance_result"
            assert payload["p_value"] == {"content": guide.strip()}
            return Query({"ok": True, "updated": False, "reason": "content unchanged"})

    @contextmanager
    def streamed_response(**_kwargs):
        yield SimpleNamespace(
            text_stream=iter([guide[:50], guide[50:]]),
            get_final_message=lambda: SimpleNamespace(
                id="msg_docs",
                model="claude-haiku-4-5-20251001",
                usage=SimpleNamespace(input_tokens=100, output_tokens=50),
            ),
        )

    monkeypatch.setattr(mihari, "_api_key_auth", lambda _request: ("u1", "f1", "rag_test"))
    monkeypatch.setattr(mihari, "get_supabase", DocumentationDB)
    monkeypatch.setattr("mcp_server._descendant_folder_ids", lambda *_: ["f1"])
    monkeypatch.setattr(
        "services.folder_summary.repo.get_latest_summary",
        lambda *_: {"content": {"sections": {"documentation": {"content": abstract}}}},
    )
    monkeypatch.setattr("services.llm.stream_complete", streamed_response)
    saved = []
    monkeypatch.setattr("services.usage_ledger.save_usage", lambda rows: saved.extend(rows))
    response = TestClient(app).post(
        "/api/mihari/documentation",
        json={"folder_id": "f1", "head_sha": "a" * 40},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "updated": False, "reason": "content unchanged"}
    assert saved[0]["source"] == "mihari"
    assert saved[0]["operation"] == "documentation"
