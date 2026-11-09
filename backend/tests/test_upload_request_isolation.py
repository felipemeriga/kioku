"""Storage and setup delays must leave unrelated requests responsive."""

import asyncio
import threading

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from auth import get_current_user
from routes import documents, drop, notion


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation",
    [
        "document_dedup",
        "document_storage",
        "drop_auth",
        "drop_storage",
        "notion_db",
        "notion_crypto",
    ],
)
async def test_slow_upload_and_notion_io_does_not_stop_health(monkeypatch, operation):
    app = FastAPI()
    app.include_router(documents.router)
    app.include_router(drop.router)
    app.include_router(notion.router)
    app.dependency_overrides[get_current_user] = lambda: "user"

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    loop_thread = threading.get_ident()
    io_threads = []

    def slow(*_args, **_kwargs):
        io_threads.append(threading.get_ident())
        entered.set()
        # A watchdog prevents a broken route from hanging the test. Correct
        # routes stay blocked until the health requests explicitly release I/O.
        release.wait(timeout=5)
        finished.set()
        raise HTTPException(status_code=503, detail="simulated upstream delay")

    monkeypatch.setattr(documents, "get_supabase", lambda: None)
    monkeypatch.setattr(documents, "check_duplicate", lambda *_: False)
    monkeypatch.setattr(drop, "check_duplicate", lambda *_: False)
    monkeypatch.setattr(drop, "_resolve_user_from_api_key", lambda *_: ("user", None))
    monkeypatch.setattr(notion, "get_supabase", lambda: None)
    targets = {
        "document_dedup": (documents, "check_duplicate"),
        "document_storage": (documents, "upload_document_to_storage"),
        "drop_auth": (drop, "_resolve_user_from_api_key"),
        "drop_storage": (drop, "upload_document_to_storage"),
        "notion_db": (notion, "get_supabase"),
        "notion_crypto": (notion, "encrypt_secret"),
    }
    module, name = targets[operation]
    monkeypatch.setattr(module, name, slow)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def upload():
            if operation.startswith("document"):
                response = await client.post(
                    "/api/documents/upload", files={"file": ("test.md", b"hello")}
                )
            elif operation.startswith("drop"):
                response = await client.post(
                    "/api/drop",
                    files={"file": ("test.md", b"hello")},
                    headers={"Authorization": "Bearer test"},
                )
            elif operation == "notion_db":
                response = await client.post(
                    "/api/notion/configs/00000000-0000-0000-0000-000000000001/sync"
                )
            else:
                response = await client.post(
                    "/api/notion/configs",
                    json={
                        "root_folder_id": "folder",
                        "notion_page_id": "page",
                        "notion_page_title": "test",
                        "integration_token": "test",
                    },
                )
            assert response.status_code == 503

        request = asyncio.create_task(upload())
        try:
            assert await asyncio.to_thread(entered.wait, 5), "Slow I/O was never reached"
            assert len(io_threads) == 1
            assert io_threads[0] != loop_thread, "Blocking I/O ran on the event-loop thread"
            for _ in range(3):
                response = await asyncio.wait_for(client.get("/api/health"), timeout=5)
                assert response.status_code == 200
                assert not finished.is_set(), "Health only completed after slow I/O finished"
                assert not request.done()
        finally:
            release.set()
            await asyncio.wait_for(request, timeout=5)
