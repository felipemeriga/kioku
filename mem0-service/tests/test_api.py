"""API tests with a fake in-memory MemoryStore (no DB, no embedder)."""

import pytest
from fastapi.testclient import TestClient

import app.main as main

AUTH = {"Authorization": "Bearer test-token"}


class FakeStore:
    """In-memory stand-in for MemoryStore, keyed by (user_id, folder_id)."""

    def __init__(self):
        self._rows: dict[tuple[str, str], list[dict]] = {}
        self._seq = 0

    def add(
        self,
        user_id,
        folder_id,
        content,
        *,
        scope,
        category,
        tags=None,
        written_by="kioku",
    ):
        bucket = self._rows.setdefault((user_id, folder_id), [])
        for m in bucket:
            if m["memory"] == content and m["metadata"]["scope"] == scope:
                return {"ok": True, "memory_id": m["id"], "duplicate": True}
        self._seq += 1
        mem_id = f"mem-{self._seq}"
        bucket.append(
            {
                "id": mem_id,
                "memory": content,
                "metadata": {"scope": scope, "category": category, "tags": tags or []},
            }
        )
        return {"ok": True, "memory_id": mem_id, "duplicate": False}

    def list(self, user_id, folder_id, *, scope="any", limit=50):
        rows = self._rows.get((user_id, folder_id), [])
        if scope in (None, "any"):
            return rows[:limit]
        return [m for m in rows if m["metadata"]["scope"] == scope][:limit]

    def search(self, user_id, folder_id, query, *, scope="any", limit=10):
        return [
            m
            for m in self.list(user_id, folder_id, scope=scope, limit=limit)
            if query in m["memory"]
        ]

    def delete(self, memory_id):
        for bucket in self._rows.values():
            for m in list(bucket):
                if m["id"] == memory_id:
                    bucket.remove(m)
                    return {"ok": True}
        return {"ok": False, "error": "not found"}

    def ping(self):
        return True, None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "store", FakeStore())
    return TestClient(main.app)


def test_add_requires_token(client):
    r = client.post(
        "/memories",
        json={
            "user_id": "u1",
            "folder_id": "f1",
            "content": "x",
            "scope": "eternal",
            "category": "preference",
        },
    )
    assert r.status_code == 401


def test_add_then_list_roundtrip(client):
    add = client.post(
        "/memories",
        headers=AUTH,
        json={
            "user_id": "u1",
            "folder_id": "f1",
            "content": "prefers tabs",
            "scope": "eternal",
            "category": "preference",
        },
    )
    assert add.status_code == 200
    body = add.json()
    assert body["ok"] is True and body["duplicate"] is False and body["memory_id"]

    listed = client.post(
        "/memories/list",
        headers=AUTH,
        json={"user_id": "u1", "folder_id": "f1", "scope": "eternal"},
    )
    assert listed.status_code == 200
    results = listed.json()["results"]
    assert any(m["memory"] == "prefers tabs" for m in results)


def test_list_is_folder_scoped(client):
    client.post(
        "/memories",
        headers=AUTH,
        json={
            "user_id": "u1",
            "folder_id": "fA",
            "content": "only in A",
            "scope": "eternal",
            "category": "note",
        },
    )
    other = client.post(
        "/memories/list", headers=AUTH, json={"user_id": "u1", "folder_id": "fB"}
    )
    assert all(m["memory"] != "only in A" for m in other.json()["results"])


def test_search_filters_by_query(client):
    client.post(
        "/memories",
        headers=AUTH,
        json={
            "user_id": "u1",
            "folder_id": "f1",
            "content": "alpha rule",
            "scope": "eternal",
            "category": "note",
        },
    )
    client.post(
        "/memories",
        headers=AUTH,
        json={
            "user_id": "u1",
            "folder_id": "f1",
            "content": "beta rule",
            "scope": "eternal",
            "category": "note",
        },
    )
    r = client.post(
        "/memories/search",
        headers=AUTH,
        json={"user_id": "u1", "folder_id": "f1", "query": "alpha"},
    )
    results = r.json()["results"]
    assert len(results) == 1 and results[0]["memory"] == "alpha rule"


def test_delete(client):
    add = client.post(
        "/memories",
        headers=AUTH,
        json={
            "user_id": "u1",
            "folder_id": "f1",
            "content": "to delete",
            "scope": "eternal",
            "category": "note",
        },
    )
    mem_id = add.json()["memory_id"]
    d = client.delete(
        f"/memories/{mem_id}", headers=AUTH, params={"user_id": "u1", "folder_id": "f1"}
    )
    assert d.status_code == 200 and d.json()["ok"] is True
