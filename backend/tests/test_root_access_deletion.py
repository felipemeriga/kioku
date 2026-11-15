"""Provider-first, owner-scoped and resumable resource removal."""

from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi import HTTPException

from services.root_access import deletion, discovery, provider, store
from services.root_access.v2_store import V2Store
from tests.test_root_access import OWNER, RESOURCE, ROOT, api, db  # noqa: F401
from tests.test_root_access_v2 import request, vdb  # noqa: F401

REF = "KIOKU_" + "a" * 64


@pytest.fixture
def workflow(db, monkeypatch):  # noqa: F811
    calls, refs = [], [REF]

    def rpc(name, args):
        calls.append(name)
        if name == "begin_access_resource_deletion":
            db.rows["access_resources"][0]["deletion_requested_at"] = "2026-11-15T00:00:00Z"
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=list(refs)))
        if name == "ack_access_resource_deletion":
            refs.remove(args["p_ref"])
            return SimpleNamespace(execute=lambda: SimpleNamespace(data=len(refs)))
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=None))

    db.rpc = rpc

    class Vault:
        down = False

        def delete(self, ref):
            calls.append("provider_delete")
            assert ref == REF
            if self.down:
                raise provider.ProviderUnavailable()

    monkeypatch.setattr(deletion, "InfisicalProvider", Vault)
    return calls, refs, Vault


def test_provider_failure_is_resumable_without_forgetting_references(db, workflow):  # noqa: F811
    calls, refs, vault = workflow
    vault.down = True
    with pytest.raises(HTTPException) as error:
        deletion.delete_resource_step(store.AccessStore(db), OWNER, ROOT, RESOURCE)
    assert error.value.status_code == 503
    assert refs == [REF]
    assert calls == ["begin_access_resource_deletion", "provider_delete"]
    assert db.rows["access_resources"][0]["deletion_requested_at"]
    vault.down = False
    assert deletion.delete_resource_step(store.AccessStore(db), OWNER, ROOT, RESOURCE) == {
        "deleted": True
    }
    assert calls[-3:] == [
        "provider_delete",
        "ack_access_resource_deletion",
        "finish_access_resource_deletion",
    ]


def test_rotation_objects_checkpoint_before_final_metadata_removal(db, workflow):  # noqa: F811
    calls, refs, _ = workflow
    refs.append(REF)
    response = deletion.delete_resource_step(store.AccessStore(db), OWNER, ROOT, RESOURCE)
    assert response.status_code == 202
    assert b"remaining" in response.body and REF.encode() not in response.body
    assert "finish_access_resource_deletion" not in calls
    assert deletion.delete_resource_step(store.AccessStore(db), OWNER, ROOT, RESOURCE)["deleted"]


def test_delete_is_owner_and_root_scoped(api, workflow):  # noqa: F811
    calls, _, _ = workflow
    response = api.delete(f"/api/root-access/{ROOT}/resources/{UUID(int=999)}")
    assert response.status_code == 404
    assert calls == []


def test_v1_v2_resolution_and_discovery_reject_pending_deletion(vdb):  # noqa: F811
    vdb.rows["access_resources"][0]["deletion_requested_at"] = "2026-11-15T00:00:00Z"
    with pytest.raises(HTTPException) as error:
        store.AccessStore(vdb).binding(OWNER, ROOT, vdb.rows["access_bindings"][0])
    assert error.value.detail["code"] == "resource_deleting"
    with pytest.raises(HTTPException) as error:
        V2Store(vdb).authorize_usage(
            OWNER, ROOT, vdb.rows["secret_devices"][0], request().usages[0], False
        )
    assert error.value.detail["code"] == "resource_deleting"
    assert discovery.discover_resources(vdb, OWNER, ROOT)["resources"] == []


@pytest.mark.parametrize("status", [200, 204, 404, 403, 500])
def test_provider_deletion_scoped_and_errors_sanitized(monkeypatch, status):
    for name, value in {
        "URL": "https://synthetic.invalid",
        "PROJECT_ID": "test-project",
        "CLIENT_ID": "synthetic-id",
        "CLIENT_SECRET": "synthetic-only",
    }.items():
        monkeypatch.setenv("KIOKU_VAULT_" + name, value)
    vault = provider.InfisicalProvider()

    def handler(req):
        if req.url.path.endswith("login"):
            return httpx.Response(200, json={"accessToken": "synthetic-token"})
        assert req.method == "DELETE" and req.url.path.endswith(REF)
        assert b'"workspaceId":"test-project"' in req.content
        return httpx.Response(status, json={"detail": "must-not-appear-in-errors"})

    monkeypatch.setattr(
        vault,
        "_client",
        lambda: httpx.Client(base_url=vault.origin, transport=httpx.MockTransport(handler)),
    )
    if status in {200, 204, 404}:
        vault.delete(REF)
    else:
        with pytest.raises(provider.ProviderUnavailable) as error:
            vault.delete(REF)
        assert "must-not-appear" not in str(error.value)
