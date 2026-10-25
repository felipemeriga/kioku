"""Unrelated requests must remain responsive while synchronous I/O is waiting."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from auth import get_current_user
from routes import cli, documents, folders, notion
from services import embeddings, retrieval


class Query:
    def __init__(self, execute):
        self._execute = execute

    def __getattr__(self, _):
        return lambda *args, **kwargs: self

    def execute(self):
        return self._execute()


async def assert_health_during_io(app, path, started, release, finished, **kwargs):
    @app.get("/health")
    async def health():
        return {"io_finished": finished.is_set()}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        pending = asyncio.create_task(client.request(kwargs.pop("method", "GET"), path, **kwargs))
        try:
            assert await asyncio.to_thread(started.wait, 2)
            response = await client.get("/health")
            assert response.json() == {"io_finished": False}
        finally:
            release.set()
        response = await pending
        assert response.status_code == 200
        return response


def blocking_io(result):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def call():
        started.set()
        try:
            assert release.wait(2), "I/O was not released while health request completed"
            return result
        finally:
            finished.set()

    return call, started, release, finished


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "module,path",
    [(folders, "/api/folders"), (documents, "/api/documents"), (notion, "/api/notion/configs")],
)
async def test_database_routes_do_not_block_health(monkeypatch, module, path):
    call, started, release, finished = blocking_io(SimpleNamespace(data=[]))
    monkeypatch.setattr(module, "get_supabase", lambda: Query(call))
    app = FastAPI()
    app.include_router(module.router)
    app.dependency_overrides[get_current_user] = lambda: "alice"
    await assert_health_during_io(app, path, started, release, finished)


@pytest.mark.asyncio
async def test_search_embedding_does_not_block_health_and_keeps_scope(monkeypatch):
    import mcp_server

    call, started, release, finished = blocking_io([0.1])
    monkeypatch.setattr(embeddings, "embed_query", lambda _: call())
    monkeypatch.setattr(
        cli,
        "get_supabase",
        lambda: Query(
            lambda: SimpleNamespace(data=[{"user_id": "alice", "scope_folder_id": "repo"}])
        ),
    )
    monkeypatch.setattr(mcp_server, "_descendant_folder_ids", lambda *_: ["repo"])
    retrieve = AsyncMock(return_value=SimpleNamespace(hits=[]))
    monkeypatch.setattr(retrieval, "retrieve_knowledge", retrieve)
    app = FastAPI()
    app.include_router(cli.router)
    await assert_health_during_io(
        app,
        "/api/cli/search",
        started,
        release,
        finished,
        method="POST",
        json={"query": "question"},
        headers={"Authorization": "Bearer rag_test"},
    )
    assert retrieve.call_args.kwargs["user_id"] == "alice"
    assert retrieve.call_args.kwargs["folder_id"] == "repo"
    assert retrieve.call_args.kwargs["embedding"] == [0.1]


@pytest.mark.asyncio
async def test_search_rejects_foreign_scope_before_embedding(monkeypatch):
    import mcp_server

    monkeypatch.setattr(
        cli,
        "get_supabase",
        lambda: Query(
            lambda: SimpleNamespace(data=[{"user_id": "alice", "scope_folder_id": "repo"}])
        ),
    )
    monkeypatch.setattr(mcp_server, "_descendant_folder_ids", lambda *_: ["repo"])

    def unexpected_embedding(_):
        raise AssertionError("Foreign scope reached embedding provider")

    monkeypatch.setattr(embeddings, "embed_query", unexpected_embedding)
    app = FastAPI()
    app.include_router(cli.router)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        response = await c.post(
            "/api/cli/search",
            json={"query": "question", "folder_id": "foreign"},
            headers={"Authorization": "Bearer rag_test"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_retrieval_audit_does_not_block_health_and_total_includes_write(monkeypatch):
    call, started, release, finished = blocking_io(None)
    monkeypatch.setattr(retrieval, "_search_docs", AsyncMock(return_value=([], 0)))
    monkeypatch.setattr(retrieval, "_log_retrieval", lambda *args, **kwargs: call())
    app = FastAPI()

    @app.get("/retrieve")
    async def retrieve():
        result = await retrieval.retrieve_knowledge(
            None,
            embedding=[],
            query_text="question",
            user_id="alice",
            folder_id=None,
        )
        return {"elapsed_ms": result.total_latency_ms}

    response = await assert_health_during_io(app, "/retrieve", started, release, finished)
    assert response.json()["elapsed_ms"] >= 0
