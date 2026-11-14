"""Root access privacy and authorization regression tests; synthetic values only."""

from copy import deepcopy
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from auth import get_current_user
from routes import root_access as routes
from services.root_access import models, provider, store

OWNER = str(uuid4())
ROOT = str(uuid4())
OTHER = str(uuid4())
RESOURCE = str(uuid4())
BINDING = str(uuid4())
ENV = str(uuid4())
DEVICE = str(uuid4())
SECRET = "synthetic-only-value-not-a-real-password"


class Query:
    def __init__(self, sb, name):
        self.sb = sb
        self.name = name
        self.filters = []
        self.columns = "*"
        self.operation = "select"
        self.payload = None
        self.cap = None

    def select(self, columns="*"):
        self.columns = columns
        return self

    def eq(self, k, v):
        self.filters.append(lambda r: r.get(k) == v)
        return self

    def gt(self, k, v):
        self.filters.append(lambda r: r.get(k, "") > v)
        return self

    def is_(self, k, v):
        self.filters.append(lambda r: r.get(k) is None)
        return self

    def limit(self, n):
        self.cap = n
        return self

    def order(self, *a, **kw):
        return self

    def insert(self, v):
        self.operation = "insert"
        self.payload = v
        return self

    def update(self, v):
        self.operation = "update"
        self.payload = v
        return self

    def upsert(self, v, **kw):
        self.operation = "upsert"
        self.payload = v
        return self

    def execute(self):
        table = self.sb.rows.setdefault(self.name, [])
        if self.operation in {"insert", "upsert"}:
            row = {"id": str(uuid4()), **deepcopy(self.payload)}
            table.append(row)
            return SimpleNamespace(data=[deepcopy(row)])
        rows = [r for r in table if all(f(r) for f in self.filters)]
        if self.cap:
            rows = rows[: self.cap]
        if self.operation == "update":
            for r in rows:
                r.update(deepcopy(self.payload))
        if self.columns != "*":
            rows = [{k: r.get(k) for k in self.columns.split(",")} for r in rows]
        return SimpleNamespace(data=deepcopy(rows))


class DB:
    def __init__(self):
        self.rows = {}

    def table(self, name):
        return Query(self, name)


@pytest.fixture
def db():
    db = DB()
    db.rows = {
        "folders": [{"id": ROOT, "user_id": OWNER, "parent_id": None}],
        "access_resources": [
            {
                "id": RESOURCE,
                "root_folder_id": ROOT,
                "user_id": OWNER,
                "name": "SES MongoDB",
                "description": "SES database",
                "type": "database",
                "aliases": ["homologação"],
                "shared": False,
                "account": "",
                "region": "",
            }
        ],
        "root_environments": [
            {
                "id": ENV,
                "root_folder_id": ROOT,
                "user_id": OWNER,
                "slug": "staging",
                "name": "Staging",
                "sensitivity": "normal",
            }
        ],
        "access_bindings": [
            {
                "id": BINDING,
                "user_id": OWNER,
                "root_folder_id": ROOT,
                "resource_id": RESOURCE,
                "environment_id": ENV,
                "consumer": "ingester",
                "field_mapping": {"MONGO_URI": "uri"},
                "clear_env": ["MONGO_URL"],
                "revision": 1,
                "enabled": True,
                "has_secret": True,
                "provider_ref": "KIOKU_"
                + OWNER.replace("-", "")
                + "_"
                + ROOT.replace("-", "")
                + "_"
                + uuid4().hex,
                "write_operation_id": None,
                "credential_expires_at": None,
            }
        ],
        "secret_devices": [
            {
                "id": DEVICE,
                "user_id": OWNER,
                "root_folder_id": ROOT,
                "credential_hash": store.digest("ksd_fake-token"),
                "label": "Mac",
                "expires_at": (store.now() + timedelta(days=1)).isoformat(),
                "revoked_at": None,
            }
        ],
        "secret_grants": [
            {
                "id": str(uuid4()),
                "user_id": OWNER,
                "root_folder_id": ROOT,
                "device_id": DEVICE,
                "binding_id": BINDING,
                "expires_at": None,
                "revoked_at": None,
            }
        ],
    }
    return db


@pytest.fixture
def api(db, monkeypatch):
    monkeypatch.setattr(routes, "get_supabase", lambda: db)
    app = FastAPI()
    app.include_router(routes.router)
    app.include_router(routes.secret_router)
    app.dependency_overrides[get_current_user] = lambda: OWNER
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def fake_provider(monkeypatch):
    class Vault:
        configured = True

        def read(self, ref):
            return {"uri": SECRET}

    monkeypatch.setattr(store, "InfisicalProvider", Vault)


def body():
    return {
        "root_id": ROOT,
        "invocation_id": str(uuid4()),
        "bindings": [{"binding_id": BINDING, "revision": 1}],
    }


def test_catalog_contains_no_provider_reference_hash_or_values(api):
    response = api.get("/api/root-access/" + ROOT)
    assert response.status_code == 200
    assert "provider_ref" not in response.text
    assert "credential_hash" not in response.text
    assert SECRET not in response.text
    assert response.json()["bindings"][0]["has_secret"] is True


@pytest.mark.parametrize("field,value", [("markdown", "😀" * 20000)])
def test_guide_utf8_bound(field, value):
    with pytest.raises(ValidationError):
        models.Guide(**{field: value, "expected_revision": 0})


@pytest.mark.parametrize(
    "name",
    [
        "LD_PRELOAD",
        "DYLD_INSERT_LIBRARIES",
        "NODE_OPTIONS",
        "PATH",
        "HOME",
        "BASH_ENV",
        "1BAD",
        "A-B",
    ],
)
def test_unsafe_mapping_names_rejected(name):
    with pytest.raises(ValidationError):
        models.Binding(
            resource_id=RESOURCE, environment_id=ENV, consumer="test", field_mapping={name: "uri"}
        )


@pytest.mark.parametrize("value", ["", "bad\x00value", "a" * 65537])
def test_invalid_credential_values_rejected_without_echo(api, value):
    response = api.post(
        f"/api/root-access/{ROOT}/bindings/{BINDING}/credential",
        json={"values": {"uri": value}, "expected_revision": 1, "idempotency_key": str(uuid4())},
    )
    assert response.status_code == 422
    assert "values" not in response.text
    assert response.json()["detail"]["code"] == "invalid_input"


def test_extra_fields_never_echoed(api):
    response = api.post(
        f"/api/root-access/{ROOT}/bindings/{BINDING}/credential",
        json={
            "values": {"uri": SECRET},
            "expected_revision": 1,
            "idempotency_key": str(uuid4()),
            "unexpected": SECRET,
        },
    )
    assert response.status_code == 422 and SECRET not in response.text


def test_secret_whitespace_preserved():
    c = models.Credential(
        values={"uri": "  sample\n "}, expected_revision=1, idempotency_key=uuid4()
    )
    assert c.values["uri"] == "  sample\n "
    assert "sample" not in repr(c)


def test_wrong_owner_and_nonroot_denied(db):
    with pytest.raises(HTTPException):
        store.AccessStore(db).catalog(OTHER, ROOT)
    db.rows["folders"][0]["parent_id"] = str(uuid4())
    with pytest.raises(HTTPException):
        store.AccessStore(db).catalog(OWNER, ROOT)


def test_resolve_injects_exact_values_only_for_device(api, fake_provider):
    response = api.post(
        "/api/secret-access/resolve",
        json=body(),
        headers={"Authorization": "Bearer ksd_fake-token"},
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["environment"] == {"MONGO_URI": SECRET}
    assert set(response.json()["clear_env"]) >= {"MONGO_URL", "MONGO_URI", "MONGODB_URL"}


@pytest.mark.parametrize("token", ["", "user-jwt", "kio_mcp-key"])
def test_jwt_and_mcp_not_secret_authorization(api, token):
    response = api.post(
        "/api/secret-access/resolve", json=body(), headers={"Authorization": "Bearer " + token}
    )
    assert response.status_code == 401 and SECRET not in response.text


@pytest.mark.parametrize(
    "change",
    [
        "revoked",
        "expired",
        "root",
        "grant",
        "grant_expired",
        "binding_revision",
        "write_pending",
        "disabled",
        "credential_expired",
    ],
)
def test_resolve_denies_revoked_or_changed_state(api, db, fake_provider, change):
    d = db.rows["secret_devices"][0]
    b = db.rows["access_bindings"][0]
    g = db.rows["secret_grants"][0]
    if change == "revoked":
        d["revoked_at"] = store.now().isoformat()
    if change == "expired":
        d["expires_at"] = (store.now() - timedelta(seconds=1)).isoformat()
    if change == "root":
        db.rows["folders"][0]["parent_id"] = OTHER
    if change == "grant":
        g["revoked_at"] = store.now().isoformat()
    if change == "grant_expired":
        g["expires_at"] = (store.now() - timedelta(seconds=1)).isoformat()
    if change == "binding_revision":
        b["revision"] = 2
    if change == "write_pending":
        b["write_operation_id"] = str(uuid4())
    if change == "disabled":
        b["enabled"] = False
    if change == "credential_expired":
        b["credential_expires_at"] = (store.now() + timedelta(seconds=30)).isoformat()
    response = api.post(
        "/api/secret-access/resolve",
        json=body(),
        headers={"Authorization": "Bearer ksd_fake-token"},
    )
    assert response.status_code in {401, 403, 404, 409}
    assert SECRET not in response.text


def test_provider_failure_safe_and_metadata_still_works(api, monkeypatch):
    class Broken:
        configured = True

        def read(self, ref):
            raise RuntimeError(SECRET)

    monkeypatch.setattr(store, "InfisicalProvider", Broken)
    response = api.post(
        "/api/secret-access/resolve",
        json=body(),
        headers={"Authorization": "Bearer ksd_fake-token"},
    )
    assert response.status_code == 503 and SECRET not in response.text
    assert api.get("/api/root-access/" + ROOT).status_code == 200


def test_revocation_during_provider_read_prevents_delivery(api, db, monkeypatch):
    class Revoking:
        def read(self, ref):
            db.rows["secret_grants"][0]["revoked_at"] = store.now().isoformat()
            return {"uri": SECRET}

    monkeypatch.setattr(store, "InfisicalProvider", Revoking)
    response = api.post(
        "/api/secret-access/resolve",
        json=body(),
        headers={"Authorization": "Bearer ksd_fake-token"},
    )
    assert response.status_code == 403 and SECRET not in response.text


def test_duplicate_variable_binding_denied_before_vault_read(api, db, fake_provider):
    other = str(uuid4())
    new = deepcopy(db.rows["access_bindings"][0])
    new["id"] = other
    db.rows["access_bindings"].append(new)
    grant = deepcopy(db.rows["secret_grants"][0])
    grant["binding_id"] = other
    db.rows["secret_grants"].append(grant)
    value = body()
    value["bindings"].append({"binding_id": other, "revision": 1})
    assert (
        api.post(
            "/api/secret-access/resolve",
            json=value,
            headers={"Authorization": "Bearer ksd_fake-token"},
        ).status_code
        == 422
    )


def test_duplicate_binding_and_unknown_inputs_denied(api):
    value = body()
    value["bindings"] *= 2
    assert api.post("/api/secret-access/resolve", json=value).status_code == 422
    value = body()
    value["secret"] = SECRET
    r = api.post("/api/secret-access/resolve", json=value)
    assert r.status_code == 422 and SECRET not in r.text


def test_malformed_json_and_large_body_dont_echo(api):
    r = api.post(
        "/api/secret-access/resolve",
        content='{"secret":"' + SECRET,
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422 and SECRET not in r.text
    r = api.post("/api/secret-access/resolve", content="a" * 400001)
    assert r.status_code == 413


def test_provider_transport_safe(monkeypatch):
    for k, v in {
        "KIOKU_VAULT_URL": "https://vault.example",
        "KIOKU_VAULT_PROJECT_ID": RESOURCE,
        "KIOKU_VAULT_CLIENT_ID": "fake",
        "KIOKU_VAULT_CLIENT_SECRET": "fake",
    }.items():
        monkeypatch.setenv(k, v)
    calls = []

    def handler(req):
        calls.append(req)
        if req.url.path.endswith("/login"):
            return httpx.Response(200, json={"accessToken": "fake"})
        return httpx.Response(200, json={"secret": {"secretValue": '{"uri":"' + SECRET + '"}'}})

    vault = provider.InfisicalProvider()
    monkeypatch.setattr(
        vault,
        "_client",
        lambda: httpx.Client(base_url=vault.origin, transport=httpx.MockTransport(handler)),
    )
    ref = "KIOKU_" + "a" * 64
    assert vault.read(ref) == {"uri": SECRET}
    assert calls[1].url.params["workspaceId"] == RESOURCE
    assert SECRET not in str(calls[1].url)


@pytest.mark.parametrize(
    "url",
    [
        "http://vault.example",
        "https://user:pw@vault.example",
        "https://vault.example/path",
        "file:///tmp/a",
    ],
)
def test_provider_rejects_insecure_or_nonorigin_url(monkeypatch, url):
    monkeypatch.setenv("KIOKU_VAULT_URL", url)
    monkeypatch.delenv("KIOKU_VAULT_ALLOW_INTERNAL_HTTP", raising=False)
    with pytest.raises(provider.ProviderUnavailable):
        provider.InfisicalProvider()


def test_metadata_discovery_never_reads_vault_or_devices(db, monkeypatch):
    from services.root_access.discovery import discover_resources, environment_guide

    class Never:
        def __init__(self):
            raise AssertionError("Discovery must not instantiate a vault")

    monkeypatch.setattr(store, "InfisicalProvider", Never)
    result = discover_resources(db, OWNER, ROOT, "homologacao", environment="staging")
    assert result["resources"][0]["id"] == RESOURCE
    text = str(result)
    assert "provider_ref" not in text and "credential_hash" not in text and SECRET not in text
    assert environment_guide(db, OWNER, ROOT)["revision"] == 0
    assert discover_resources(db, OWNER, ROOT, "SES", environment="production")["resources"] == []


def test_discovery_scope_and_ambiguity(db):
    from services.root_access.discovery import discover_resources

    with pytest.raises(HTTPException):
        discover_resources(db, OTHER, ROOT, "SES")
    resource = deepcopy(db.rows["access_resources"][0])
    resource["id"] = str(uuid4())
    db.rows["access_resources"].append(resource)
    binding = deepcopy(db.rows["access_bindings"][0])
    binding["id"] = str(uuid4())
    binding["resource_id"] = resource["id"]
    db.rows["access_bindings"].append(binding)
    assert discover_resources(db, OWNER, ROOT, "SES")["requires_explicit_selection"] is True


def test_aws_mapping_controls_default_chain(db):
    db.rows["access_resources"][0]["type"] = "cloud"
    binding = deepcopy(db.rows["access_bindings"][0])
    with pytest.raises(HTTPException):
        store.AccessStore(db).binding(OWNER, ROOT, binding)
    binding["field_mapping"] = {
        "AWS_ACCESS_KEY_ID": "access_key",
        "AWS_SECRET_ACCESS_KEY": "secret_key",
    }
    value = store.AccessStore(db).binding(OWNER, ROOT, binding)
    assert "AWS_PROFILE" in value["clear_env"]
    assert "AWS_WEB_IDENTITY_TOKEN_FILE" in value["clear_env"]
    assert "AWS_CONTAINER_CREDENTIALS_FULL_URI" in value["clear_env"]


def test_unrecognized_poll_never_contains_generated_device_token(api, db):
    db.rpc = lambda name, args: SimpleNamespace(
        execute=lambda: SimpleNamespace(data={"status": "expired"})
    )
    response = api.post(
        "/api/secret-access/enroll/poll", json={"request_id": str(uuid4()), "device_code": "a" * 40}
    )
    assert response.status_code == 410 and "ksd_" not in response.text


def test_expiry_after_provider_io_blocks_delivery(api, db, monkeypatch):
    t = store.now()
    db.rows["access_bindings"][0]["credential_expires_at"] = (t + timedelta(seconds=90)).isoformat()
    monkeypatch.setattr(store, "now", lambda: t)

    class Slow:
        def read(self, ref):
            monkeypatch.setattr(store, "now", lambda: t + timedelta(seconds=120))
            return {"uri": SECRET}

    monkeypatch.setattr(store, "InfisicalProvider", Slow)
    r = api.post(
        "/api/secret-access/resolve",
        json=body(),
        headers={"Authorization": "Bearer ksd_fake-token"},
    )
    assert r.status_code == 409 and SECRET not in r.text


def test_control_variable_names_case_insensitive():
    for value in ("path", "home", "systemroot", "aws_profile", "dyld_INSERT_LIBRARIES"):
        with pytest.raises(ValueError):
            models.env_name(value)


@pytest.mark.parametrize("present,state", [(True, "completed"), (False, "cancelled")])
def test_failed_write_recovery_via_api_without_values(api, db, monkeypatch, present, state):
    op = str(uuid4())
    binding = db.rows["access_bindings"][0]
    monkeypatch.setenv("KIOKU_VAULT_WRITE_HMAC_KEY", "x" * 40)

    class Vault:
        configured = True

        def write(self, ref, values):
            raise provider.ProviderUnavailable()

        def exists(self, ref):
            return present

    monkeypatch.setattr(store, "InfisicalProvider", Vault)

    def rpc(name, args):
        def execute():
            if name == "reserve_secret_write":
                binding["write_operation_id"] = op
                db.rows["secret_write_operations"] = [
                    {
                        "id": op,
                        "binding_id": BINDING,
                        "user_id": OWNER,
                        "root_folder_id": ROOT,
                        "status": "pending",
                        "provider_ref": args["p_ref"],
                        "credential_expires_at": None,
                    }
                ]
                return SimpleNamespace(data={"status": "pending", "provider_ref": args["p_ref"]})
            assert name in {"finish_secret_write", "cancel_secret_write"}
            binding["write_operation_id"] = None
            binding["revision"] += 1
            return SimpleNamespace(data=binding["revision"])

        return SimpleNamespace(execute=execute)

    db.rpc = rpc
    r = api.post(
        f"/api/root-access/{ROOT}/bindings/{BINDING}/credential",
        json={"expected_revision": 1, "idempotency_key": op, "values": {"uri": SECRET}},
    )
    assert r.status_code == 503 and SECRET not in r.text
    catalog = api.get("/api/root-access/" + ROOT).json()
    assert catalog["bindings"][0]["pending_operation_id"] == op
    assert "provider_ref" not in str(catalog)
    r = api.post(f"/api/root-access/{ROOT}/bindings/{BINDING}/credential/reconcile", json={})
    assert r.status_code == 200 and r.json()["state"] == state
    assert r.json()["revision"] == 2
    assert api.get("/api/root-access/" + ROOT).json()["bindings"][0]["pending_operation_id"] is None


def test_uncertain_recovery_preserves_pending_state(api, db, monkeypatch):
    op = str(uuid4())
    db.rows["access_bindings"][0]["write_operation_id"] = op
    db.rows["secret_write_operations"] = [
        {
            "id": op,
            "binding_id": BINDING,
            "user_id": OWNER,
            "root_folder_id": ROOT,
            "status": "pending",
            "provider_ref": "KIOKU_" + "a" * 64,
        }
    ]

    class Down:
        def exists(self, ref):
            raise provider.ProviderUnavailable()

    monkeypatch.setattr(store, "InfisicalProvider", Down)
    r = api.post(f"/api/root-access/{ROOT}/bindings/{BINDING}/credential/reconcile", json={})
    assert r.status_code == 503
    assert db.rows["access_bindings"][0]["write_operation_id"] == op


def test_provider_reference_within_upstream_route_bound():
    reference = "KIOKU_" + store.digest(OWNER + ":" + ROOT + ":" + str(uuid4()))
    assert len(reference) <= 100
    assert provider.InfisicalProvider._reference(reference) == reference


def test_safe_routes_generate_correlation_ids_for_all_outcomes(api):
    from uuid import UUID

    results = [
        api.get("/api/root-access/" + ROOT),
        api.post("/api/secret-access/resolve", json=body()),
        api.post("/api/secret-access/resolve", json={}),
    ]
    for response in results:
        assert response.headers["Cache-Control"] == "no-store"
        assert UUID(response.headers["X-Request-ID"])
    assert len({r.headers["X-Request-ID"] for r in results}) == 3
