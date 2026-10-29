"""Connection protocol/ownership tests without production credentials or services."""

import hashlib
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from auth import get_current_user
from routes import remotes


def memory_message(folder_id=None):
    content = "A durable user correction"
    return {
        "type": "memory_post",
        "protocol": 1,
        "event_id": "a" * 64,
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        "folder_id": folder_id or str(uuid4()),
        "session_id": "session-1",
        "source": "claude_code",
        "record_position": 1,
        "event_time": datetime.now(timezone.utc).isoformat(),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "provenance": "user",
        "sensitivity": "normal",
        "content": content,
    }


class Query:
    def __init__(self, rows):
        self.rows = rows
        self.filters = {}
        self.operation = "select"
        self.values = None

    def select(self, *_):
        return self

    def eq(self, key, value):
        self.filters[key] = value
        return self

    def order(self, *_):
        return self

    def upsert(self, values, **_):
        self.operation, self.values = "upsert", values
        return self

    def update(self, values):
        self.operation, self.values = "update", values
        return self

    def execute(self):
        if self.operation == "upsert":
            key = (self.values["user_id"], self.values["id"])
            row = self.rows.setdefault(key, {"created_at": remotes.now_iso(), "connected": False})
            row.update(self.values)
            return SimpleNamespace(data=[deepcopy(row)])
        matches = [
            row
            for row in self.rows.values()
            if all(row.get(k) == v for k, v in self.filters.items())
        ]
        if self.operation == "update":
            for row in matches:
                row.update(self.values)
        return SimpleNamespace(data=deepcopy(matches))


@pytest.fixture
def setup(monkeypatch):
    rows = {}
    monkeypatch.setattr(remotes, "table", lambda: Query(rows))
    app = FastAPI()
    app.include_router(remotes.router)

    def user(request: Request):
        user_id = request.headers.get("X-Test-User")
        if not user_id:
            raise HTTPException(401)
        return user_id

    app.dependency_overrides[get_current_user] = user
    with TestClient(app) as client:
        yield client, rows


def register(client, user="alice", machine_id=None, secret=None):
    body = {
        "id": machine_id or str(uuid4()),
        "secret": secret or "a" * 64,
        "name": "Laptop",
        "platform": "linux-x64",
        "version": "0.4.0",
    }
    response = client.post("/api/remotes/register", json=body, headers={"X-Test-User": user})
    assert response.status_code == 200
    return body


def hello(socket, machine):
    socket.send_json({"type": "hello", "id": machine["id"], "secret": machine["secret"]})
    assert socket.receive_json()["type"] == "ready"


def listing(client, user="alice"):
    return client.get("/api/remotes", headers={"X-Test-User": user}).json()


def test_registration_is_idempotent_owned_and_secret_is_not_returned(setup):
    client, rows = setup
    machine = register(client)
    register(client, machine_id=machine["id"])
    register(client, user="bob", machine_id=machine["id"], secret="b" * 64)
    assert len(rows) == 2
    assert len(listing(client)) == 1
    assert len(listing(client, "bob")) == 1
    assert listing(client)[0]["online"] is False
    assert "token_hash" not in listing(client)[0]
    assert machine["secret"] not in str(rows)


def test_register_and_listing_require_user_authentication(setup):
    client, _ = setup
    assert client.get("/api/remotes").status_code == 401
    body = register(client)
    assert client.post("/api/remotes/register", json=body).status_code == 401


def test_socket_authentication_heartbeat_and_disconnect_presence(setup):
    client, _ = setup
    machine = register(client)
    with client.websocket_connect("/api/remotes/connect") as socket:
        hello(socket, machine)
        assert listing(client)[0]["online"] is True
        socket.send_json({"type": "heartbeat"})
        assert socket.receive_json() == {"type": "ack"}
    # Closing the socket and persisting disconnect run asynchronously.
    deadline = time.monotonic() + 2
    while listing(client)[0]["online"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert listing(client)[0]["online"] is False
    assert listing(client)[0]["last_seen"] is not None


def test_authenticated_reconnect_updates_reported_version(setup):
    client, _ = setup
    machine = register(client)
    with client.websocket_connect("/api/remotes/connect") as socket:
        socket.send_json(
            {
                "type": "hello",
                "id": machine["id"],
                "secret": machine["secret"],
                "version": "0.6.13",
            }
        )
        assert socket.receive_json()["type"] == "ready"
        assert listing(client)[0]["version"] == "0.6.13"


def test_invalid_secret_cannot_change_reported_version(setup):
    client, _ = setup
    machine = register(client)
    with client.websocket_connect("/api/remotes/connect") as socket:
        socket.send_json(
            {
                "type": "hello",
                "id": machine["id"],
                "secret": "b" * 64,
                "version": "9.9.9",
            }
        )
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    assert listing(client)[0]["version"] == "0.4.0"


def test_invalid_credentials_do_not_claim_presence(setup):
    client, _ = setup
    machine = register(client)
    with client.websocket_connect("/api/remotes/connect") as socket:
        socket.send_json({"type": "hello", "id": machine["id"], "secret": "b" * 64})
        with pytest.raises(WebSocketDisconnect) as error:
            socket.receive_json()
        assert error.value.code == 4401
    assert listing(client)[0]["online"] is False


def test_old_connection_cannot_heartbeat_or_clear_new_connection(setup):
    client, _ = setup
    machine = register(client)
    with client.websocket_connect("/api/remotes/connect") as old:
        hello(old, machine)
        with client.websocket_connect("/api/remotes/connect") as new:
            hello(new, machine)
            old.send_json({"type": "heartbeat"})
            with pytest.raises(WebSocketDisconnect) as error:
                old.receive_json()
            assert error.value.code == 4409
            new.send_json({"type": "heartbeat"})
            assert new.receive_json() == {"type": "ack"}
            assert listing(client)[0]["online"] is True


def test_stale_heartbeat_marks_crashed_backend_connection_offline(setup):
    client, rows = setup
    machine = register(client)
    row = rows[("alice", machine["id"])]
    row.update(
        connected=True, last_seen=(datetime.now(timezone.utc) - timedelta(seconds=91)).isoformat()
    )
    assert listing(client)[0]["online"] is False


def test_oversized_and_malformed_hello_close_without_presence(setup):
    client, _ = setup
    for value in ["x" * 1025, "[]", "not-json"]:
        with client.websocket_connect("/api/remotes/connect") as socket:
            socket.send_text(value)
            with pytest.raises(WebSocketDisconnect) as error:
                socket.receive_json()
            assert error.value.code == 4400


def test_unresponsive_initial_handshake_is_closed(setup, monkeypatch):
    client, _ = setup

    async def timed_out(*_):
        import asyncio

        raise asyncio.TimeoutError

    monkeypatch.setattr(remotes, "receive_small_json", timed_out)
    with client.websocket_connect("/api/remotes/connect") as socket:
        with pytest.raises(WebSocketDisconnect) as error:
            socket.receive_json()
        assert error.value.code == 4400


@pytest.mark.parametrize("fraction", ["", ".1", ".12", ".123", ".1234", ".12345", ".123456"])
def test_postgres_timestamp_precision_is_supported_on_python310(fraction):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S") + fraction + "+00:00"
    assert remotes.public_machine({"last_seen": timestamp, "connected": True})["online"] is True


def test_disconnect_persists_inside_cancelled_asgi_scope(setup):
    import asyncio
    import json
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import anyio

    client, rows = setup
    machine = register(client)
    release_worker = threading.Event()
    worker_started = threading.Event()

    def occupied_worker():
        worker_started.set()
        release_worker.wait(5)

    async def cancelled_connection():
        try:
            with anyio.CancelScope() as scope:

                class Socket:
                    received = False

                    async def accept(self):
                        pass

                    async def receive_text(self):
                        if not self.received:
                            self.received = True
                            return json.dumps({"type": "hello", **machine})
                        scope.cancel()
                        raise WebSocketDisconnect(1000)

                    async def send_json(self, _):
                        loop = asyncio.get_running_loop()
                        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
                        loop.run_in_executor(None, occupied_worker)
                        assert worker_started.wait(1)

                    async def close(self, **_):
                        await anyio.sleep(0)

                await remotes.connect(Socket())
        finally:
            release_worker.set()

    anyio.run(cancelled_connection)
    row = rows[("alice", machine["id"])]
    assert row["connection_id"] is not None
    assert row["connected"] is False


def inventory_report(folder_id):
    return {
        "name": "Felipe's MacBook",
        "os_name": "macOS",
        "os_id": "macos",
        "architecture": "arm64",
        "repositories": [
            {
                "id": "c" * 64,
                "folder_id": folder_id,
                "name": "kioku",
                "path": "/home/user/kioku",
                "agents": ["claude", "codex"],
                "initialized_at": remotes.now_iso(),
                "available": True,
            }
        ],
        "warnings": [],
    }


def test_inventory_is_owned_fenced_and_does_not_claim_running_agents(setup, monkeypatch):
    client, rows = setup
    folder = str(uuid4())
    monkeypatch.setattr(
        remotes, "owned_repo_ids", lambda user, ids: {folder} if user == "alice" else set()
    )
    machine = register(client)
    with client.websocket_connect("/api/remotes/connect") as socket:
        hello(socket, machine)
        data = inventory_report(folder)
        socket.send_json({"type": "inventory", "revision": "c" * 64, "data": data})
        assert socket.receive_json() == {"type": "inventory_ack", "revision": "c" * 64}
        row = listing(client)[0]
        assert row["inventory"][0]["agents"] == ["claude", "codex"]
        assert row["os_name"] == "macOS"
        assert row["inventory_updated_at"]
        assert "running" not in str(row)
        foreign = str(uuid4())
        data["repositories"][0]["folder_id"] = foreign
        socket.send_json({"type": "inventory", "revision": "d" * 64, "data": data})
        assert socket.receive_json()["type"] == "inventory_ack"
        assert listing(client)[0]["inventory"] == []
        assert listing(client)[0]["warnings"][0]["code"] == "folder_unavailable"
        assert listing(client, "bob") == []
    assert len(rows) == 1


def test_corrupt_registry_retains_last_good_inventory_and_recovers_warnings(setup, monkeypatch):
    client, _ = setup
    folder = str(uuid4())
    monkeypatch.setattr(remotes, "owned_repo_ids", lambda *_: {folder})
    machine = register(client)
    with client.websocket_connect("/api/remotes/connect") as socket:
        hello(socket, machine)
        data = inventory_report(folder)
        for warnings in [
            [],
            [{"code": "registry_unreadable", "observed_at": remotes.now_iso()}],
            [],
        ]:
            data["warnings"] = warnings
            socket.send_json({"type": "inventory", "revision": "c" * 64, "data": data})
            assert socket.receive_json()["type"] == "inventory_ack"
            assert len(listing(client)[0]["inventory"]) == 1
            assert [item["code"] for item in listing(client)[0]["warnings"]] == [
                item["code"] for item in warnings
            ]
        data["repositories"][0]["agents"] = ["running"]
        socket.send_json({"type": "inventory", "revision": "c" * 64, "data": data})
        assert socket.receive_json() == {"type": "inventory_error"}
        assert len(listing(client)[0]["inventory"]) == 1
        assert listing(client)[0]["warnings"][0]["code"] == "inventory_rejected"
        socket.send_json({"type": "heartbeat"})
        assert socket.receive_json() == {"type": "ack"}


def test_custom_name_is_owned_and_survives_reregistration(setup):
    client, _ = setup
    machine = register(client)
    url = f"/api/remotes/{machine['id']}"
    assert (
        client.patch(
            url, json={"name": "Home workstation"}, headers={"X-Test-User": "bob"}
        ).status_code
        == 404
    )
    assert (
        client.patch(
            url, json={"name": "Home workstation"}, headers={"X-Test-User": "alice"}
        ).status_code
        == 200
    )
    register(client, machine_id=machine["id"])
    assert listing(client)[0]["name"] == "Home workstation"
    assert (
        client.patch(url, json={"name": "bad\nname"}, headers={"X-Test-User": "alice"}).status_code
        == 422
    )
    client.patch(url, json={"name": None}, headers={"X-Test-User": "alice"})
    assert listing(client)[0]["name"] == "Laptop"


def test_memory_ack_requires_enabled_capability_and_successful_storage(setup, monkeypatch):
    client, _ = setup
    machine = register(client)
    calls = []
    monkeypatch.setenv("KIOKU_MEMORY_CAPTURE_ENABLED", "true")

    def accept(event, user_id, machine_id):
        calls.append((event.event_id, user_id, machine_id))
        return "stored"

    monkeypatch.setattr(remotes, "accept_event", accept)
    with client.websocket_connect("/api/remotes/connect") as socket:
        socket.send_json({"type": "hello", "id": machine["id"], "secret": machine["secret"]})
        assert "memory_post_v1" in socket.receive_json()["capabilities"]
        socket.send_json(memory_message())
        assert socket.receive_json() == {
            "type": "memory_ack",
            "event_id": "a" * 64,
            "status": "stored",
        }
        assert calls == [("a" * 64, "alice", machine["id"])]


def test_memory_storage_failure_nacks_without_ack(setup, monkeypatch):
    client, _ = setup
    machine = register(client)
    monkeypatch.setenv("KIOKU_MEMORY_CAPTURE_ENABLED", "true")

    def fail(*_):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(remotes, "accept_event", fail)
    with client.websocket_connect("/api/remotes/connect") as socket:
        hello(socket, machine)
        socket.send_json(memory_message())
        assert socket.receive_json() == {
            "type": "memory_nack",
            "event_id": "a" * 64,
            "code": "storage_unavailable",
            "retryable": True,
        }


def test_old_backend_capability_is_absent_when_capture_disabled(setup, monkeypatch):
    client, _ = setup
    machine = register(client)
    monkeypatch.delenv("KIOKU_MEMORY_CAPTURE_ENABLED", raising=False)
    with client.websocket_connect("/api/remotes/connect") as socket:
        socket.send_json({"type": "hello", "id": machine["id"], "secret": machine["secret"]})
        assert "capabilities" not in socket.receive_json()
        socket.send_json(memory_message())
        assert socket.receive_json()["code"] == "disabled"
