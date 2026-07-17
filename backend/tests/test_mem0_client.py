"""Contract tests for the self-hosted Mem0 HTTP client.

No network: we monkeypatch `services.mem0_sync.http.call` with a fake that
records requests and returns canned service responses.
"""

from __future__ import annotations

import services.mem0_sync.http as http
from services.mem0_sync.client import Mem0AppClient, get_client_for_folder


class FakeHTTP:
    """Records (method, path, body) and replays queued responses."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict | None]] = []
        self.responses: dict[tuple[str, str], dict] = {}

    def call(self, method, path, json=None):
        self.calls.append((method, path, json))
        # match on (method, path) or (method, path-prefix for DELETE)
        for (m, p), resp in self.responses.items():
            if m == method and (p == path or (p.endswith("*") and path.startswith(p[:-1]))):
                return resp
        return {}


def _patch_http(monkeypatch) -> FakeHTTP:
    fake = FakeHTTP()
    monkeypatch.setattr(http, "call", fake.call)
    return fake


def test_add_returns_service_shape(monkeypatch):
    fake = _patch_http(monkeypatch)
    fake.responses[("POST", "/memories")] = {"ok": True, "memory_id": "m1", "duplicate": False}
    c = Mem0AppClient(user_id="u1", folder_id="f1")
    res = c.add("hello", scope="eternal", category="preference", tags=["x"])
    assert res["ok"] is True and res["memory_id"] == "m1" and res["duplicate"] is False
    # request carried scope/category/tags/user/folder
    _, path, body = fake.calls[-1]
    assert path == "/memories"
    assert body["user_id"] == "u1" and body["folder_id"] == "f1"
    assert body["scope"] == "eternal" and body["category"] == "preference" and body["tags"] == ["x"]


def test_add_duplicate_backfills_existing_id(monkeypatch):
    fake = _patch_http(monkeypatch)
    fake.responses[("POST", "/memories")] = {"ok": True, "memory_id": "m9", "duplicate": True}
    res = Mem0AppClient("u1", "f1").add("dup", scope="eternal", category="note")
    assert res["duplicate"] is True and res["existing_id"] == "m9"  # mcp save_memory reads this


def test_add_degrades_on_transport_error(monkeypatch):
    fake = _patch_http(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(http, "call", boom)
    res = Mem0AppClient("u1", "f1").add("x", scope="eternal", category="note")
    assert res["ok"] is False and "connection refused" in res["error"]


def test_list_eternal_returns_records(monkeypatch):
    fake = _patch_http(monkeypatch)
    recs = [{"id": "m1", "memory": "prefers tabs", "metadata": {"scope": "eternal"}}]
    fake.responses[("POST", "/memories/list")] = {"results": recs}
    out = Mem0AppClient("u1", "f1").list_eternal(limit=50)
    assert out == recs
    _, path, body = fake.calls[-1]
    assert path == "/memories/list" and body["scope"] == "eternal"


def test_search_degrades_to_empty(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(http, "call", boom)
    assert Mem0AppClient("u1", "f1").search("q") == []


def test_ping_ok(monkeypatch):
    fake = _patch_http(monkeypatch)
    fake.responses[("GET", "/health")] = {"ok": True, "error": None}
    ok, err = Mem0AppClient("u1", "f1").ping()
    assert ok is True and err is None


# ── get_client_for_folder repo gating ────────────────────────────────────
class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return type("R", (), {"data": self._rows})()


class _FakeSB:
    def __init__(self, rows):
        self._rows = rows

    def table(self, *a, **k):
        return _FakeQuery(self._rows)


def test_get_client_for_repo_folder():
    sb = _FakeSB([{"kind": "repo"}])
    c = get_client_for_folder(sb, "f1", "u1")
    assert isinstance(c, Mem0AppClient) and c.folder_id == "f1" and c.user_id == "u1"


def test_get_client_for_non_repo_folder_returns_none():
    assert get_client_for_folder(_FakeSB([{"kind": "folder"}]), "f1", "u1") is None


def test_get_client_for_missing_folder_returns_none():
    assert get_client_for_folder(_FakeSB([]), "f1", "u1") is None
