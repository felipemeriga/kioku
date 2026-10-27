import httpx
from fastapi.testclient import TestClient

from auth import get_current_user
from main import app
from routes import briefing


class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return _Resp(self._data)


class _SB:
    def __init__(self, tables):
        self._tables = tables

    def table(self, name):
        return _Q(self._tables.get(name, []))


def test_index_status_includes_generation_timestamps():
    sb = _SB(
        {
            "repo_graph_meta": [
                {
                    "last_indexed_sha": "abc",
                    "node_count": 10,
                    "edge_count": 20,
                    "updated_at": "2026-10-06T00:00:00+00:00",
                }
            ],
            "code_chunks": [{"created_at": "2026-10-06T01:00:00+00:00"}],
            "repo_documentation": [{"generated_at": "2026-10-05T00:00:00+00:00"}],
        }
    )
    latest = {
        "sections": {
            "architecture": {"updated_at": "2026-10-06T02:24:03+00:00", "updated_by": "mihari"},
            "overview": {"updated_at": "2026-10-06T02:24:04+00:00", "updated_by": "mihari"},
        }
    }
    out = briefing._index_status(sb, "f1", "u1", {"checked_at": "t", "head_sha": "h"}, latest)
    assert out["architecture_at"] == "2026-10-06T02:24:03+00:00"
    assert out["architecture_by"] == "mihari"
    assert out["overview_at"] == "2026-10-06T02:24:04+00:00"
    assert out["detailed_doc_at"] == "2026-10-05T00:00:00+00:00"


def test_index_status_separates_review_from_content_change():
    sb = _SB(
        {
            "repo_graph_meta": [],
            "code_chunks": [],
            "repo_documentation": [{"generated_at": "2026-09-01T00:00:00+00:00"}],
        }
    )
    marker = {"reviewed_at": "2026-10-27T12:00:00+00:00", "head_sha": "a" * 40}
    fresh = {
        "section_reviews": {"architecture": marker, "overview": marker, "documentation": marker}
    }
    latest = {
        "content": {
            "sections": {
                "architecture": {"updated_at": "2026-09-01T00:00:00+00:00"},
                "overview": {"updated_at": "2026-09-01T00:00:00+00:00"},
            }
        }
    }
    out = briefing._index_status(sb, "f1", "u1", fresh, latest)
    assert out["briefing_reviewed_at"] == marker["reviewed_at"]
    assert out["briefing_reviewed_sha"] == marker["head_sha"]
    assert out["architecture_at"] == "2026-09-01T00:00:00+00:00"
    assert out["detailed_doc_at"] == "2026-09-01T00:00:00+00:00"


def test_index_status_reads_architecture_from_content_sections_only():
    """architecture lives ONLY in content.sections — top-level sections lacks it."""
    sb = _SB(
        {
            "repo_graph_meta": [],
            "code_chunks": [],
            "repo_documentation": [],
        }
    )
    latest = {
        # top-level sections only has activity — no architecture key
        "sections": {
            "activity": {"updated_at": "2026-10-06T00:00:00+00:00", "updated_by": "mihari"},
        },
        "content": {
            "sections": {
                "architecture": {
                    "updated_at": "2026-10-05T12:00:00+00:00",
                    "updated_by": "agent_mcp",
                },
            }
        },
    }
    out = briefing._index_status(sb, "f1", "u1", None, latest)
    assert out["architecture_at"] == "2026-10-05T12:00:00+00:00"
    assert out["architecture_by"] == "agent_mcp"


def test_index_status_content_overrides_stale_top_level_section():
    """Mihari's atomic content.sections patch is visible in Status."""
    sb = _SB(
        {
            "repo_graph_meta": [],
            "code_chunks": [],
            "repo_documentation": [],
        }
    )
    latest = {
        "sections": {
            "architecture": {
                "updated_at": "2026-10-06T10:00:00+00:00",
                "updated_by": "user_ui",
            },
        },
        "content": {
            "sections": {
                "architecture": {
                    "updated_at": "2026-10-07T12:00:00+00:00",
                    "updated_by": "mihari",
                },
            }
        },
    }
    out = briefing._index_status(sb, "f1", "u1", None, latest)
    assert out["architecture_at"] == "2026-10-07T12:00:00+00:00"
    assert out["architecture_by"] == "mihari"


def test_index_status_handles_missing(monkeypatch):
    sb = _SB({"repo_graph_meta": [], "code_chunks": [], "repo_documentation": []})
    out = briefing._index_status(sb, "f1", "u1", None, None)
    assert out["architecture_at"] is None
    assert out["detailed_doc_at"] is None
    assert out["graph_at"] is None


def test_status_returns_job_completion_independent_of_graph_timestamp():
    fresh = {
        "index_refresh_started_at": "2026-10-23T03:05:56Z",
        "index_refresh_finished_at": "2026-10-23T03:06:02Z",
        "index_refresh_error": None,
        "sections_refresh_error": "Refresh failed",
    }
    out = briefing._index_status(_SB({}), "f1", "u1", fresh, None)
    assert out["graph_at"] is None
    assert out["index_refresh_finished_at"] == fresh["index_refresh_finished_at"]
    assert out["sections_refresh_error"] == "Refresh failed"


def test_status_route_returns_payload(monkeypatch):
    sb = _SB(
        {
            "repo_graph_meta": [],
            "code_chunks": [],
            "repo_documentation": [],
        }
    )
    monkeypatch.setattr(briefing, "get_supabase", lambda: sb)
    monkeypatch.setattr(
        briefing, "_folder_must_be_repo", lambda s, f, u: {"id": f, "kind": "repo", "name": "r"}
    )
    monkeypatch.setattr(briefing, "get_latest_summary", lambda s, f, u: None)
    app.dependency_overrides[get_current_user] = lambda: "u1"
    try:
        client = TestClient(app)
        r = client.get("/api/folders/f1/status")
        assert r.status_code == 200
        assert "architecture_at" in r.json()
        assert "graph_at" in r.json()
    finally:
        app.dependency_overrides.clear()


def _refresh_setup(monkeypatch):
    sb = _SB({})
    monkeypatch.setattr(briefing, "get_supabase", lambda: sb)
    monkeypatch.setattr(
        briefing, "_folder_must_be_repo", lambda s, f, u: {"id": f, "kind": "repo", "name": "r"}
    )
    app.dependency_overrides[get_current_user] = lambda: "u1"


def test_refresh_bad_target(monkeypatch):
    _refresh_setup(monkeypatch)
    try:
        r = TestClient(app).post("/api/folders/f1/refresh", json={"target": "nope"})
        assert r.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_refresh_proxies_202(monkeypatch):
    _refresh_setup(monkeypatch)
    monkeypatch.setenv("MIHARI_TRIGGER_TOKEN", "secret")

    class _R:
        status_code = 202

        def json(self):
            return {"started": True}

    monkeypatch.setattr(briefing.httpx, "post", lambda *a, **k: _R())
    try:
        r = TestClient(app).post("/api/folders/f1/refresh", json={"target": "index"})
        assert r.status_code == 202
        assert r.json()["started"] is True
    finally:
        app.dependency_overrides.clear()


def test_refresh_mihari_unreachable_503(monkeypatch):
    _refresh_setup(monkeypatch)
    monkeypatch.setenv("MIHARI_TRIGGER_TOKEN", "secret")

    def _boom(*a, **k):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(briefing.httpx, "post", _boom)
    try:
        r = TestClient(app).post("/api/folders/f1/refresh", json={"target": "index"})
        assert r.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_refresh_no_token_503(monkeypatch):
    _refresh_setup(monkeypatch)
    monkeypatch.delenv("MIHARI_TRIGGER_TOKEN", raising=False)
    try:
        r = TestClient(app).post("/api/folders/f1/refresh", json={"target": "index"})
        assert r.status_code == 503
    finally:
        app.dependency_overrides.clear()


def test_refresh_uses_mihari_address_and_token(monkeypatch):
    _refresh_setup(monkeypatch)
    monkeypatch.setenv("MIHARI_TRIGGER_TOKEN", "new-secret")
    monkeypatch.setenv("MIHARI_URL", "http://kioku-mihari:8787/")
    calls = []

    class Response:
        status_code = 202

        def json(self):
            return {"started": True}

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(briefing.httpx, "post", post)
    try:
        response = TestClient(app).post("/api/folders/f1/refresh", json={"target": "index"})
        assert response.status_code == 202
        assert calls[0][0] == "http://kioku-mihari:8787/run"
        assert calls[0][1]["headers"]["X-Mihari-Token"] == "new-secret"
    finally:
        app.dependency_overrides.clear()


def test_refresh_legacy_environment_is_supported(monkeypatch):
    _refresh_setup(monkeypatch)
    monkeypatch.delenv("MIHARI_TRIGGER_TOKEN", raising=False)
    monkeypatch.delenv("MIHARI_URL", raising=False)
    monkeypatch.setenv("WATCHER_TRIGGER_TOKEN", "old-secret")
    monkeypatch.setenv("WATCHER_URL", "http://old-service:8787")
    calls = []

    class Response:
        status_code = 202

        def json(self):
            return {"started": True}

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr(briefing.httpx, "post", post)
    try:
        response = TestClient(app).post("/api/folders/f1/refresh", json={"target": "index"})
        assert response.status_code == 202
        assert calls[0][0] == "http://old-service:8787/run"
        assert calls[0][1]["headers"]["X-Watcher-Token"] == "old-secret"
    finally:
        app.dependency_overrides.clear()


def test_mihari_and_legacy_registration_routes_require_same_auth():
    client = TestClient(app)
    for prefix in ("/api/mihari", "/api/watcher"):
        response = client.post(f"{prefix}/key")
        assert response.status_code == 401
        assert response.json()["detail"] == "Bearer api key required"
