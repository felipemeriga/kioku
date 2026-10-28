import json
from contextlib import contextmanager
from types import SimpleNamespace

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
        raise AssertionError(name)


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


def test_review_plan_recovers_from_invalid_model_reply(monkeypatch):
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
    assert response.status_code == 200
    assert set(response.json()["selected"]) == set(mihari.REVIEWED_SECTIONS)


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
            assert name == "repo_documentation"
            return Query([{"content": guide, "abstract": abstract}])

    @contextmanager
    def streamed_response(**_kwargs):
        yield SimpleNamespace(text_stream=iter([guide[:50], guide[50:]]))

    monkeypatch.setattr(mihari, "_api_key_auth", lambda _request: ("u1", "f1", "rag_test"))
    monkeypatch.setattr(mihari, "get_supabase", DocumentationDB)
    monkeypatch.setattr("mcp_server._descendant_folder_ids", lambda *_: ["f1"])
    monkeypatch.setattr(
        "services.folder_summary.repo.get_latest_summary",
        lambda *_: {"content": {"sections": {"documentation": {"content": abstract}}}},
    )
    monkeypatch.setattr("services.llm.stream_complete", streamed_response)
    response = TestClient(app).post(
        "/api/mihari/documentation",
        json={"folder_id": "f1", "head_sha": "a" * 40},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True, "updated": False, "reason": "content unchanged"}
