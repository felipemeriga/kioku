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
            "architecture": {"updated_at": "2026-10-06T02:24:03+00:00", "updated_by": "watcher"},
            "overview": {"updated_at": "2026-10-06T02:24:04+00:00", "updated_by": "watcher"},
        }
    }
    out = briefing._index_status(sb, "f1", "u1", {"checked_at": "t", "head_sha": "h"}, latest)
    assert out["architecture_at"] == "2026-10-06T02:24:03+00:00"
    assert out["architecture_by"] == "watcher"
    assert out["overview_at"] == "2026-10-06T02:24:04+00:00"
    assert out["detailed_doc_at"] == "2026-10-05T00:00:00+00:00"


def test_index_status_handles_missing(monkeypatch):
    sb = _SB({"repo_graph_meta": [], "code_chunks": [], "repo_documentation": []})
    out = briefing._index_status(sb, "f1", "u1", None, None)
    assert out["architecture_at"] is None
    assert out["detailed_doc_at"] is None
    assert out["graph_at"] is None


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
    monkeypatch.setenv("WATCHER_TRIGGER_TOKEN", "secret")

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


def test_refresh_watcher_unreachable_503(monkeypatch):
    _refresh_setup(monkeypatch)
    monkeypatch.setenv("WATCHER_TRIGGER_TOKEN", "secret")

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
    monkeypatch.delenv("WATCHER_TRIGGER_TOKEN", raising=False)
    try:
        r = TestClient(app).post("/api/folders/f1/refresh", json={"target": "index"})
        assert r.status_code == 503
    finally:
        app.dependency_overrides.clear()
