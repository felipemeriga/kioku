"""Route tests for the simplified mem0 proxy (self-hosted service backend).

Handlers are called directly (matching this repo's route-test style) with a
fake supabase and a monkeypatched get_client_for_folder.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import routes.mem0 as mem0_routes

FOLDER = "00000000-0000-0000-0000-000000000001"


class FakeClient:
    def __init__(self, healthy=True):
        self.deleted: list[str] = []
        self._healthy = healthy

    def list_eternal(self, limit=100):
        return [{"id": "m1", "memory": "prefers tabs", "metadata": {"scope": "eternal"}}]

    def delete(self, memory_id):
        self.deleted.append(memory_id)
        return {"ok": True}

    def ping(self):
        return (self._healthy, None if self._healthy else "down")


def _wire(monkeypatch, client):
    monkeypatch.setattr(mem0_routes, "get_supabase", lambda: object())
    monkeypatch.setattr(mem0_routes, "get_client_for_folder", lambda sb, f, u: client)


@pytest.mark.asyncio
async def test_list_rules_for_repo(monkeypatch):
    _wire(monkeypatch, FakeClient())
    out = await mem0_routes.list_rules(root_folder_id=FOLDER, user_id="u1")
    assert out["rules"][0]["id"] == "m1"


@pytest.mark.asyncio
async def test_list_rules_non_repo_404(monkeypatch):
    _wire(monkeypatch, None)  # not a repo folder
    with pytest.raises(HTTPException) as ei:
        await mem0_routes.list_rules(root_folder_id=FOLDER, user_id="u1")
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_rule_calls_client(monkeypatch):
    c = FakeClient()
    _wire(monkeypatch, c)
    out = await mem0_routes.delete_rule(memory_id="mem-42", root_folder_id=FOLDER, user_id="u1")
    assert out == {"ok": True} and c.deleted == ["mem-42"]


@pytest.mark.asyncio
async def test_delete_rule_non_repo_404(monkeypatch):
    _wire(monkeypatch, None)
    with pytest.raises(HTTPException) as ei:
        await mem0_routes.delete_rule(memory_id="m1", root_folder_id=FOLDER, user_id="u1")
    assert ei.value.status_code == 404


@pytest.mark.asyncio
async def test_status_available_and_healthy(monkeypatch):
    _wire(monkeypatch, FakeClient(healthy=True))
    out = await mem0_routes.status(root_folder_id=FOLDER, user_id="u1")
    assert out == {"available": True, "healthy": True, "error": None}


@pytest.mark.asyncio
async def test_status_not_a_repo(monkeypatch):
    _wire(monkeypatch, None)
    out = await mem0_routes.status(root_folder_id=FOLDER, user_id="u1")
    assert out == {"available": False, "reason": "not a repo folder"}
