"""Exercise the real Supabase query builders against a tenant-aware fake database."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from supabase import create_client
from supabase.lib.client_options import SyncClientOptions

from routes import notion
from services.notion_sync.folder_paths import ensure_notion_folder_path
from services.queue import tasks


@pytest.fixture
def db():
    folders = [
        {"id": "root", "user_id": "owner", "parent_id": None, "name": "root"},
        {"id": "foreign", "user_id": "other", "parent_id": None, "name": "foreign"},
        {"id": "foreign-child", "user_id": "other", "parent_id": "root", "name": "notion"},
    ]
    configs = []
    writes = []

    def handler(request):
        table = request.url.path.rsplit("/", 1)[-1]
        rows = folders if table == "folders" else configs
        assert table in {"folders", "notion_sync_configs"}
        if request.method == "POST":
            record = json.loads(request.content)
            record = {"id": f"created-{len(writes)}", **record}
            writes.append((table, record))
            rows.append(record)
            return httpx.Response(201, json=[record])
        assert request.method == "GET"
        selected = rows[:]
        for field, value in request.url.params.items():
            if field in {"id", "user_id", "parent_id", "name"}:
                assert value.startswith("eq.")
                selected = [r for r in selected if r[field] == value[3:]]
        if table == "folders":
            assert request.url.params["user_id"] == "eq.owner"
        return httpx.Response(200, json=selected)

    client = create_client(
        "https://notion.test.invalid",
        "test-only",
        options=SyncClientOptions(
            httpx_client=httpx.Client(transport=httpx.MockTransport(handler))
        ),
    )
    return SimpleNamespace(client=client, folders=folders, configs=configs, writes=writes)


def test_creates_and_reuses_only_owned_folder_chain(db):
    arguments = dict(user_id="owner", root_folder_id="root", ancestor_titles=["Cosm", "Sprint"])
    leaf, path = ensure_notion_folder_path(db.client, **arguments)
    assert path == "Cosm / Sprint"
    assert leaf == "created-2"
    assert [record["name"] for _, record in db.writes] == ["notion", "Cosm", "Sprint"]
    assert db.writes[0][1]["parent_id"] == "root"
    assert all(record["user_id"] == "owner" for _, record in db.writes)
    assert ensure_notion_folder_path(db.client, **arguments) == (leaf, path)
    assert len(db.writes) == 3


def test_empty_chain_returns_owned_notion_root(db):
    assert ensure_notion_folder_path(
        db.client, user_id="owner", root_folder_id="root", ancestor_titles=[]
    ) == ("created-0", "")


@pytest.mark.parametrize("root", ["foreign", "missing"])
def test_foreign_or_missing_root_never_creates_folder(db, root):
    with pytest.raises(HTTPException) as error:
        ensure_notion_folder_path(
            db.client, user_id="owner", root_folder_id=root, ancestor_titles=["x"]
        )
    assert error.value.status_code == 404
    assert db.writes == []


@pytest.mark.parametrize("root", ["foreign", "missing", "root"])
def test_config_checks_owner_before_encrypt_or_insert(db, monkeypatch, root):
    monkeypatch.setattr(notion, "get_supabase", lambda: db.client)
    encrypt = Mock(return_value="encrypted-test-token")
    monkeypatch.setattr(notion, "encrypt_secret", encrypt)
    body = notion.ConnectRequest(
        root_folder_id=root,
        notion_page_id="p",
        notion_page_title="Page",
        integration_token="test-only",
    )
    if root == "root":
        assert notion._insert_config(body, "owner")["root_folder_id"] == "root"
        encrypt.assert_called_once_with("test-only")
        assert len(db.writes) == 1
    else:
        with pytest.raises(HTTPException) as error:
            notion._insert_config(body, "owner")
        assert error.value.status_code == 404
        encrypt.assert_not_called()
        assert db.writes == []


@pytest.mark.parametrize("stage", ["page", "sync"])
def test_stale_queued_foreign_root_rejected_before_notion_or_ai(db, monkeypatch, stage):
    monkeypatch.setattr(tasks, "get_supabase_thread_safe", lambda: db.client)
    for name in (
        "decrypt_secret",
        "NotionClient",
        "contextualize_chunks",
        "embed_batch",
        "mark_running",
    ):
        monkeypatch.setattr(
            tasks, name, Mock(side_effect=AssertionError("work started before authorization"))
        )
    payload = {
        "job_id": "job",
        "config_id": "config",
        "user_id": "owner",
        "root_folder_id": "foreign",
    }
    db.configs.append({"id": "config", "user_id": "owner", "root_folder_id": "foreign"})
    function = (
        tasks._ingest_notion_page_task_impl if stage == "page" else tasks._notion_sync_task_impl
    )
    with pytest.raises(HTTPException) as error:
        asyncio.run(function({}, payload))
    assert error.value.status_code == 404
    assert db.writes == []


def test_page_picker_accepts_token_only_in_post_body(monkeypatch):
    client = Mock()
    client.iter_pages_edited_since.return_value = [
        SimpleNamespace(page_id="p", title="Selected page")
    ]
    factory = Mock(return_value=client)
    monkeypatch.setattr(notion, "NotionClient", factory)
    app = FastAPI()
    app.include_router(notion.router)
    app.dependency_overrides[notion.get_current_user] = lambda: "owner"
    with TestClient(app) as http:
        response = http.post(
            "/api/notion/pages", json={"integration_token": "test-only", "query": "Selected"}
        )
        assert response.status_code == 200
        assert response.json() == [{"id": "p", "title": "Selected page"}]
        factory.assert_called_once_with("test-only")
        assert http.get("/api/notion/pages?integration_token=test-only").status_code == 405
        assert http.post("/api/notion/pages?integration_token=test-only").status_code == 422
        assert factory.call_count == 1
