"""Synthetic-only V2 credential privacy, authorization and delivery contracts."""

import json
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from pydantic import ValidationError

from services.root_access import discovery, store
from services.root_access import v2_models as m
from services.root_access import v2_store as v2
from tests.test_root_access import (  # noqa: F401
    BINDING,
    DEVICE,
    ENV,
    OWNER,
    RESOURCE,
    ROOT,
    api,
    db,
)

CID, UID = str(uuid4()), str(uuid4())
VALUE = "synthetic-v2-only-not-a-real-secret"


@pytest.fixture
def vdb(db):  # noqa: F811
    db.rows["access_credentials"] = [
        {
            "id": CID,
            "user_id": OWNER,
            "root_folder_id": ROOT,
            "resource_id": RESOURCE,
            "environment_id": ENV,
            "label": "Staging",
            "kind": "uri",
            "fields": ["connection"],
            "enabled": True,
            "revision": 2,
            "has_secret": True,
            "provider_ref": "opaque-reference",
            "credential_expires_at": None,
            "write_operation_id": None,
            "fingerprint": None,
            "legacy_binding_id": None,
        }
    ]
    db.rows["access_usages"] = [
        {
            "id": UID,
            "user_id": OWNER,
            "root_folder_id": ROOT,
            "credential_id": CID,
            "name": "ingester",
            "consumer": "ses/ingester",
            "enabled": True,
            "revision": 1,
            "legacy_binding_id": None,
            "delivery": {
                "kind": "env",
                "field_mapping": {"MONGO_URI": "connection"},
                "clear_env": [],
            },
        }
    ]
    db.rows["secret_usage_grants"] = [
        {
            "id": str(uuid4()),
            "user_id": OWNER,
            "root_folder_id": ROOT,
            "device_id": DEVICE,
            "usage_id": UID,
            "usage_revision": 1,
            "allowed_fields": ["connection"],
            "capabilities": ["env"],
            "expires_at": None,
            "revoked_at": None,
        }
    ]
    return db


def request(**kwargs):
    return m.ResolveV2(
        root_id=ROOT,
        invocation_id=uuid4(),
        usages=[{"usage_id": UID, "revision": 1, "credential_revision": 2}],
        **kwargs,
    )


@pytest.fixture
def provider(monkeypatch):
    class Provider:
        configured = True
        calls = 0
        effect = None
        values = {"connection": VALUE}

        def read(self, ref):
            Provider.calls += 1
            if Provider.effect:
                Provider.effect()
            return deepcopy(Provider.values)

    monkeypatch.setattr(v2, "InfisicalProvider", Provider)
    return Provider


@pytest.mark.parametrize(
    "delivery",
    [
        {"kind": "env", "field_mapping": {"PATH": "connection"}},
        {"kind": "env", "field_mapping": {"node_options": "connection"}},
        {"kind": "argv", "arguments": [{"kind": "field", "field": "connection"}]},
        {
            "kind": "file",
            "format": "xml",
            "patches": [{"path": ["db"], "field": "connection"}],
            "destination": {"kind": "arg", "name": "--config"},
        },
        {
            "kind": "file",
            "format": "json",
            "patches": [{"path": ["__proto__"], "field": "connection"}],
            "destination": {"kind": "arg", "name": "--config"},
        },
        {
            "kind": "file",
            "format": "json",
            "patches": [{"path": ["../config"], "field": "connection"}],
            "destination": {"kind": "arg", "name": "--config"},
        },
        {
            "kind": "file",
            "format": "json",
            "patches": [
                {"path": ["db"], "field": "connection"},
                {"path": ["db", "uri"], "field": "connection"},
            ],
            "destination": {"kind": "env", "name": "CONFIG_FILE"},
        },
        {
            "kind": "file",
            "format": "json",
            "patches": [{"path": ["db"], "field": "connection"}],
            "destination": {"kind": "arg", "name": "--config=/etc/passwd"},
        },
        {"kind": "ssh", "host": "-oProxyCommand=sh", "user": "root", "host_key": "not-a-key"},
    ],
)
def test_rejects_unsafe_delivery(delivery):
    with pytest.raises(ValidationError):
        m.Usage(credential_id=CID, name="test", consumer="app", delivery=delivery)


def test_resolve_returns_only_selected_field(vdb, provider):
    result = v2.V2Store(vdb).resolve_v2("ksd_fake-token", request())
    assert result["deliveries"][0]["environment"] == {"MONGO_URI": VALUE}
    assert "provider_ref" not in json.dumps(result)
    assert VALUE not in json.dumps(vdb.rows)
    assert provider.calls == 1


def test_two_recipes_reuse_single_instance_without_duplicate_provider_reads(vdb, provider):
    usage = deepcopy(vdb.rows["access_usages"][0])
    usage["id"] = str(uuid4())
    usage["delivery"]["field_mapping"] = {"OTHER_URI": "connection"}
    vdb.rows["access_usages"].append(usage)
    grant = deepcopy(vdb.rows["secret_usage_grants"][0])
    grant.update(id=str(uuid4()), usage_id=usage["id"])
    vdb.rows["secret_usage_grants"].append(grant)
    body = request()
    body.usages.append(m.RequestedUsage(usage_id=usage["id"], revision=1, credential_revision=2))
    result = v2.V2Store(vdb).resolve_v2("ksd_fake-token", body)
    assert len(result["deliveries"]) == 2
    assert provider.calls == 1


@pytest.mark.parametrize(
    "mutation,code",
    [
        (
            lambda d: d.rows["secret_usage_grants"][0].update(revoked_at=store.now().isoformat()),
            "access_denied",
        ),
        (
            lambda d: d.rows["secret_usage_grants"][0].update(allowed_fields=["other"]),
            "access_denied",
        ),
        (lambda d: d.rows["secret_usage_grants"][0].update(capabilities=["file"]), "access_denied"),
        (lambda d: d.rows["access_usages"][0].update(revision=2), "access_denied"),
        (lambda d: d.rows["access_credentials"][0].update(revision=3), "binding_changed"),
        (
            lambda d: d.rows["access_credentials"][0].update(write_operation_id=str(uuid4())),
            "binding_changed",
        ),
        (
            lambda d: d.rows["access_credentials"][0].update(
                credential_expires_at=(store.now() + timedelta(seconds=30)).isoformat()
            ),
            "credential_expired",
        ),
        (
            lambda d: d.rows["access_credentials"][0].update(root_folder_id=str(uuid4())),
            "access_denied",
        ),
    ],
)
def test_pre_authorization_denies_without_provider_io(vdb, provider, mutation, code):
    mutation(vdb)
    with pytest.raises(HTTPException) as error:
        v2.V2Store(vdb).resolve_v2("ksd_fake-token", request())
    assert error.value.detail["code"] == code
    assert provider.calls == 0


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.rows["secret_devices"][0].update(revoked_at=store.now().isoformat()),
        lambda d: d.rows["secret_usage_grants"][0].update(revoked_at=store.now().isoformat()),
        lambda d: d.rows["secret_usage_grants"][0].update(capabilities=[]),
        lambda d: d.rows["access_credentials"][0].update(revision=3),
        lambda d: d.rows["access_credentials"][0].update(
            credential_expires_at=(store.now() + timedelta(seconds=1)).isoformat()
        ),
        lambda d: d.rows["access_usages"][0].update(enabled=False),
    ],
)
def test_post_provider_rechecks_prevent_delivery(vdb, provider, mutation):
    provider.effect = lambda: mutation(vdb)
    with pytest.raises(HTTPException):
        v2.V2Store(vdb).resolve_v2("ksd_fake-token", request())
    assert provider.calls == 1
    assert not any(e["outcome"] == "allowed" for e in vdb.rows.get("secret_access_events", []))


def test_metadata_never_has_values_or_provider_reference(vdb, provider):
    result = v2.V2Store(vdb).catalog_v2(OWNER, ROOT)
    found = discovery.discover_resources(vdb, OWNER, ROOT, "SES", "staging")
    serialized = json.dumps([result, found])
    assert "opaque-reference" not in serialized
    assert VALUE not in serialized
    assert "credential_hash" not in serialized
    assert provider.calls == 0


def test_create_credential_requires_no_mapping_or_secret(vdb):
    value = {
        "resource_id": RESOURCE,
        "environment_id": ENV,
        "label": "",
        "kind": "uri",
        "fields": ["connection"],
        "enabled": True,
    }
    result = v2.V2Store(vdb).create_credential(OWNER, ROOT, value)
    assert result["resource_id"] == RESOURCE
    assert len(vdb.rows["access_usages"]) == 1
    assert "provider_ref" not in result


def test_shared_has_no_environment_account_region_requirement(vdb):
    vdb.rows["access_resources"][0]["shared"] = True
    result = v2.V2Store(vdb).create_credential(
        OWNER,
        ROOT,
        {
            "resource_id": RESOURCE,
            "environment_id": None,
            "label": "",
            "kind": "api_key",
            "fields": ["api_key"],
            "enabled": True,
        },
    )
    assert result["environment_id"] is None


def test_existing_schema_cannot_change_after_store(vdb):
    old = deepcopy(vdb.rows["access_credentials"][0])
    body = {
        k: old[k] for k in ("resource_id", "environment_id", "label", "kind", "fields", "enabled")
    }
    body.update(expected_revision=2, fields=["password"])
    with pytest.raises(HTTPException):
        v2.V2Store(vdb).update_credential(OWNER, ROOT, CID, body)
    assert vdb.rows["access_credentials"][0] == old


def test_ssh_encrypted_key_requires_correct_passphrase():
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.BestAvailableEncryption(b"synthetic-passphrase"),
    ).decode()
    fingerprint = v2.ssh_fingerprint({"private_key": private, "passphrase": "synthetic-passphrase"})
    assert fingerprint.startswith("SHA256:")
    with pytest.raises(HTTPException) as error:
        v2.ssh_fingerprint({"private_key": private, "passphrase": "wrong"})
    assert private not in str(error.value.detail)


def test_raw_argv_requires_both_grant_and_invocation_ack(vdb, provider):
    vdb.rows["access_usages"][0]["delivery"] = {
        "kind": "argv",
        "arguments": [
            {"kind": "literal", "value": "--uri"},
            {"kind": "field", "field": "connection"},
        ],
        "allow_raw_secret_argv": True,
    }
    vdb.rows["secret_usage_grants"][0]["capabilities"] = ["argv", "raw_secret_argv"]
    with pytest.raises(HTTPException):
        v2.V2Store(vdb).resolve_v2("ksd_fake-token", request())
    assert provider.calls == 0
    result = v2.V2Store(vdb).resolve_v2("ksd_fake-token", request(allow_raw_secret_argv=True))
    assert result["deliveries"][0]["arguments"][1] == {"kind": "secret", "value": VALUE}


def test_aws_pair_atomic_and_missing_optional_token_clears_inherited(vdb, provider):
    credential = vdb.rows["access_credentials"][0]
    credential.update(kind="aws", fields=["access_key_id", "secret_access_key", "session_token"])
    mapping = {
        "AWS_ACCESS_KEY_ID": "access_key_id",
        "AWS_SECRET_ACCESS_KEY": "secret_access_key",
        "AWS_SESSION_TOKEN": "session_token",
    }
    vdb.rows["access_usages"][0]["delivery"] = {
        "kind": "env",
        "field_mapping": mapping,
        "clear_env": [],
    }
    vdb.rows["secret_usage_grants"][0]["allowed_fields"] = list(mapping.values())
    provider.values = {"access_key_id": VALUE, "secret_access_key": VALUE + "-secret"}
    result = v2.V2Store(vdb).resolve_v2("ksd_fake-token", request())
    assert set(result["deliveries"][0]["environment"]) == {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
    }
    assert {"AWS_SESSION_TOKEN", "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_PROFILE"} <= set(
        result["clear_env"]
    )


def test_generic_file_cannot_set_aws_control_path(vdb):
    with pytest.raises(HTTPException):
        v2.V2Store(vdb).usage_valid(
            OWNER,
            ROOT,
            {
                "credential_id": CID,
                "delivery": {
                    "kind": "file",
                    "format": "toml",
                    "source_template": "",
                    "patches": [{"path": ["uri"], "field": "connection"}],
                    "destination": {"kind": "env", "name": "AWS_SHARED_CREDENTIALS_FILE"},
                },
            },
        )


def test_route_validation_never_echoes_values(api):  # noqa: F811
    result = api.post(
        f"/api/root-access/{ROOT}/credentials/{CID}/value",
        json={
            "expected_revision": 1,
            "idempotency_key": str(uuid4()),
            "values": {"connection": VALUE + "\x00"},
        },
    )
    assert result.status_code == 422
    assert VALUE not in result.text
    assert result.headers["cache-control"] == "no-store"


def test_partial_region_patch_preserves_schema_and_uses_cas(vdb):
    result = v2.V2Store(vdb).update_credential(
        OWNER, ROOT, CID, {"expected_revision": 2, "region": "us-east-1"}
    )
    assert result["region"] == "us-east-1"
    assert result["fields"] == ["connection"]
    assert result["revision"] == 3
    with pytest.raises(HTTPException):
        v2.V2Store(vdb).update_credential(
            OWNER, ROOT, CID, {"expected_revision": 2, "region": "us-west-2"}
        )


def test_partial_invalid_metadata_is_sanitized_422(vdb):
    with pytest.raises(HTTPException) as error:
        v2.V2Store(vdb).update_credential(OWNER, ROOT, CID, {"expected_revision": 2, "kind": None})
    assert error.value.status_code == 422


def test_recipe_edit_revokes_effective_grant_until_reapproved(vdb, provider):
    usage = deepcopy(vdb.rows["access_usages"][0])
    body = {k: usage[k] for k in ("credential_id", "name", "consumer", "delivery", "enabled")}
    body["expected_revision"] = 1
    body["delivery"]["field_mapping"] = {"OTHER_URI": "connection"}
    v2.V2Store(vdb).update_usage(OWNER, ROOT, UID, body)
    req = request()
    req.usages[0].revision = 2
    with pytest.raises(HTTPException) as error:
        v2.V2Store(vdb).resolve_v2("ksd_fake-token", req)
    assert error.value.status_code == 403
    assert provider.calls == 0


def test_aws_file_bundle_descriptor_and_region(vdb, provider):
    vdb.rows["access_credentials"][0].update(
        kind="aws", fields=["access_key_id", "secret_access_key"], region="us-east-1"
    )
    vdb.rows["access_usages"][0]["delivery"] = {
        "kind": "file",
        "format": "toml",
        "source_template": "[default]\n",
        "patches": [
            {"path": ["default", "aws_access_key_id"], "field": "access_key_id"},
            {"path": ["default", "aws_secret_access_key"], "field": "secret_access_key"},
        ],
        "destination": {"kind": "env", "name": "AWS_SHARED_CREDENTIALS_FILE"},
    }
    vdb.rows["secret_usage_grants"][0].update(
        allowed_fields=["access_key_id", "secret_access_key"], capabilities=["file"]
    )
    provider.values = {"access_key_id": VALUE, "secret_access_key": VALUE + "-secret"}
    result = v2.V2Store(vdb).resolve_v2("ksd_fake-token", request())
    delivery = result["deliveries"][0]
    assert delivery["environment"] == {"AWS_REGION": "us-east-1"}
    assert len(delivery["patches"]) == 2
    assert "AWS_PROFILE" in result["clear_env"]


def test_aws_values_reject_control_characters(vdb):
    row = vdb.rows["access_credentials"][0]
    row.update(kind="aws", fields=["access_key_id", "secret_access_key"])
    with pytest.raises(HTTPException):
        v2.V2Store(vdb).validate_values(
            row, {"access_key_id": "synthetic\n", "secret_access_key": VALUE}
        )


def test_ssh_excessive_bcrypt_work_rejected_before_crypto(monkeypatch):
    import base64
    import struct

    def ssh_string(v):
        return struct.pack(">I", len(v)) + v

    blob = (
        b"openssh-key-v1\x00"
        + ssh_string(b"aes256-ctr")
        + ssh_string(b"bcrypt")
        + ssh_string(ssh_string(b"salt") + struct.pack(">I", 2**30))
    )
    key = (
        "-----BEGIN OPENSSH PRIVATE KEY-----\n"
        + base64.b64encode(blob).decode()
        + "\n-----END OPENSSH PRIVATE KEY-----"
    )
    monkeypatch.setattr(
        v2.serialization,
        "load_ssh_private_key",
        lambda *a, **kw: pytest.fail("expensive crypto called"),
    )
    with pytest.raises(HTTPException):
        v2.ssh_fingerprint({"private_key": key, "passphrase": "synthetic"})
