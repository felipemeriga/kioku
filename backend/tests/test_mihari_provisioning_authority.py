import json
import time
from types import SimpleNamespace

import httpx
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from supabase import create_client
from supabase.lib.client_options import SyncClientOptions

import auth
from routes import mihari

REMOTE = "git@github.com:example/private.git"
JWT_KEY = "test-only-owner-session-key-at-least-thirty-two-bytes"


def owner_header(owner="owner"):
    token = jwt.encode(
        {"sub": owner, "aud": "authenticated", "exp": int(time.time()) + 60}, JWT_KEY
    )
    return {"X-Kioku-Owner-Authorization": "Bearer " + token}


@pytest.fixture
def fixture(monkeypatch):
    state = {"repos": [], "keys": [], "writes": [], "decryptions": [], "race": False}

    def handler(request):
        table = "repos" if request.url.path.endswith("watched_repos") else "keys"
        if request.method == "PATCH" and state["race"]:
            state["repos"][0]["folder_id"] = "sibling"
        selected = state[table]
        for key, value in request.url.params.multi_items():
            if value.startswith("eq."):
                selected = [row for row in selected if str(row.get(key)) == value[3:]]
            if value.startswith("in.("):
                values = value[4:-1].split(",")
                selected = [row for row in selected if row.get(key) in values]
        if request.method in {"PATCH", "POST"}:
            state["writes"].append(request)
            data = json.loads(request.content)
            if request.method == "POST":
                data.setdefault("id", "new")
                data.setdefault("created_at", "now")
                state[table].append(data)
                selected = [data]
            else:
                for row in selected:
                    row.update(data)
        return httpx.Response(200, json=selected)

    db = create_client(
        "https://provisioning.test.invalid",
        "test-only",
        options=SyncClientOptions(
            httpx_client=httpx.Client(transport=httpx.MockTransport(handler))
        ),
    )
    monkeypatch.setattr(mihari, "get_supabase", lambda: db)
    monkeypatch.setattr(mihari, "_api_key_auth", lambda _: ("owner", "allowed", "rag_test"))
    monkeypatch.setattr("mcp_server._descendant_folder_ids", lambda *_: ["allowed", "child"])
    monkeypatch.setattr(auth, "_get_signing_key", lambda _: (SimpleNamespace(key=JWT_KEY), "HS256"))
    monkeypatch.setattr(mihari, "encrypt_secret", lambda _: "test-encrypted")
    monkeypatch.setattr(mihari, "_generate_ed25519", lambda: ("private", "public", "fingerprint"))

    def decrypt(value):
        state["decryptions"].append(value)
        return "private-test-only"

    monkeypatch.setattr(mihari, "decrypt_secret", decrypt)
    monkeypatch.setattr(mihari, "_ls_remote_with_key", lambda *_: ("abc123", ""))
    app = FastAPI()
    app.include_router(mihari.router, prefix="/api/mihari")
    return TestClient(app), state


def known(folder="allowed", branch="main"):
    return {
        "id": "registered",
        "user_id": "owner",
        "folder_id": folder,
        "branch": branch,
        "remote_url": REMOTE,
    }


def key():
    return {
        "user_id": "owner",
        "private_key_encrypted": "cipher",
        "public_key": "public",
        "fingerprint": "fingerprint",
    }


@pytest.mark.parametrize("prior", [None, known("sibling"), known(branch="private-branch")])
def test_scoped_key_cannot_provision_rebind_or_change_branch(fixture, prior):
    client, state = fixture
    state["repos"] = [prior] if prior else []
    response = client.post("/api/mihari/repos", json={"folder_id": "allowed", "remote_url": REMOTE})
    assert response.status_code == 403
    assert not state["writes"]


def test_exact_binding_refresh_retains_scoped_key_support(fixture):
    client, state = fixture
    state["repos"] = [known()]
    response = client.post("/api/mihari/repos", json={"folder_id": "allowed", "remote_url": REMOTE})
    assert response.status_code == 200
    request = state["writes"][0]
    assert request.url.params["folder_id"] == "eq.allowed"
    assert request.url.params["branch"] == "eq.main"
    assert request.url.params["user_id"] == "eq.owner"


@pytest.mark.parametrize(
    "headers, status",
    [({"X-Kioku-Owner-Authorization": "Bearer invalid"}, 401), (owner_header("other"), 403)],
)
def test_invalid_supplied_session_never_falls_back_to_key(fixture, headers, status):
    client, state = fixture
    state["repos"] = [known()]
    state["keys"] = [key()]
    for endpoint, payload in [
        ("repos", {"folder_id": "allowed", "remote_url": REMOTE}),
        ("test-access", {"remote_url": REMOTE}),
        ("key", None),
    ]:
        response = client.post("/api/mihari/" + endpoint, json=payload, headers=headers)
        assert response.status_code == status
    assert not state["writes"]
    assert not state["decryptions"]


@pytest.mark.parametrize("prior", [None, known("sibling"), known(branch="private-branch")])
def test_same_owner_session_can_authorize_provisioning(fixture, prior):
    client, state = fixture
    state["repos"] = [prior] if prior else []
    response = client.post(
        "/api/mihari/repos",
        json={"folder_id": "allowed", "remote_url": REMOTE},
        headers=owner_header(),
    )
    assert response.status_code == 200
    assert state["repos"][0]["folder_id"] == "allowed"
    assert state["repos"][0]["branch"] == "main"


def test_concurrent_owner_rebind_cannot_be_overwritten_by_scoped_key(fixture):
    client, state = fixture
    state["repos"] = [known()]
    state["race"] = True
    response = client.post("/api/mihari/repos", json={"folder_id": "allowed", "remote_url": REMOTE})
    assert response.status_code == 409
    assert state["repos"][0]["folder_id"] == "sibling"
    assert len(state["repos"]) == 1


@pytest.mark.parametrize("prior", [None, known("sibling"), known(branch="other-branch")])
def test_key_cannot_probe_global_ssh_access_outside_registered_scope(fixture, prior):
    client, state = fixture
    state["repos"] = [prior] if prior else []
    state["keys"] = [key()]
    response = client.post("/api/mihari/test-access", json={"remote_url": REMOTE})
    assert response.status_code == 403
    assert not state["decryptions"]


def test_known_branch_can_be_probed_by_scoped_key(fixture):
    client, state = fixture
    state["repos"] = [known("child")]
    state["keys"] = [key()]
    response = client.post("/api/mihari/test-access", json={"remote_url": REMOTE})
    assert response.status_code == 200
    assert len(state["decryptions"]) == 1


def test_unknown_remote_can_be_probed_with_owner_session(fixture):
    client, state = fixture
    state["keys"] = [key()]
    response = client.post(
        "/api/mihari/test-access", json={"remote_url": REMOTE}, headers=owner_header()
    )
    assert response.status_code == 200
    assert len(state["decryptions"]) == 1


def test_key_creation_needs_owner_but_public_key_read_does_not(fixture):
    client, state = fixture
    assert client.post("/api/mihari/key").status_code == 403
    assert not state["writes"]
    assert client.post("/api/mihari/key", headers=owner_header()).status_code == 200
    assert client.post("/api/mihari/key").json()["created"] is False
