"""Credential instances and versioned delivery recipes, without metadata secret leakage."""

import base64
import hmac
import json
import os
import struct
from hashlib import sha256
from uuid import uuid4

from cryptography.hazmat.primitives import serialization

from services.root_access.provider import InfisicalProvider, ProviderUnavailable
from services.root_access.store import AccessStore, digest, expired, fail, now
from services.root_access.v2_models import (
    CredentialInstance,
    Usage,
    usage_capabilities,
    usage_fields,
)

PUBLIC_CREDENTIAL = (
    "id,resource_id,environment_id,label,kind,fields,enabled,revision,has_secret,"
    "credential_expires_at,write_operation_id,fingerprint,legacy_binding_id,region"
)
PUBLIC_USAGE = "id,credential_id,name,consumer,delivery,enabled,revision,legacy_binding_id"
PUBLIC_USAGE_GRANT = (
    "id,device_id,usage_id,usage_revision,allowed_fields,capabilities,expires_at,revoked_at"
)
AWS_CLEAR = [
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_PROFILE",
    "AWS_DEFAULT_PROFILE",
    "AWS_CONFIG_FILE",
    "AWS_SHARED_CREDENTIALS_FILE",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_ROLE_ARN",
    "AWS_ROLE_SESSION_NAME",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
]


def public_credential(row):
    result = {k: row.get(k) for k in PUBLIC_CREDENTIAL.split(",") if k != "write_operation_id"}
    result["pending_operation_id"] = row.get("write_operation_id")
    return result


def ssh_fingerprint(values):
    """Validate key and passphrase together; return public fingerprint only."""
    password = values.get("passphrase")
    password = password.encode() if password else None
    raw = values["private_key"].encode()
    try:
        if raw.startswith(b"-----BEGIN OPENSSH PRIVATE KEY-----"):
            # Bound attacker-controlled bcrypt work before handing encrypted keys
            # to the library. A tiny PEM can otherwise request billions of rounds.
            encoded = b"".join(raw.splitlines()[1:-1])
            decoded = base64.b64decode(encoded, validate=True)
            if not decoded.startswith(b"openssh-key-v1\x00"):
                raise ValueError("Invalid key")
            pos = len(b"openssh-key-v1\x00")
            parts = []
            for _ in range(3):
                size = struct.unpack_from(">I", decoded, pos)[0]
                pos += 4
                if size > len(decoded) - pos:
                    raise ValueError("Invalid key")
                parts.append(decoded[pos : pos + size])
                pos += size
            if parts[1] == b"bcrypt":
                salt_size = struct.unpack_from(">I", parts[2], 0)[0]
                rounds = struct.unpack_from(">I", parts[2], 4 + salt_size)[0]
                if not 1 <= rounds <= 128:
                    raise ValueError("Unsupported key work factor")
            elif parts[1] != b"none":
                raise ValueError("Unsupported key derivation")
            key = serialization.load_ssh_private_key(raw, password=password)
        else:
            key = serialization.load_pem_private_key(raw, password=password)
        public = key.public_key().public_bytes(
            serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
        )
        blob = base64.b64decode(public.split()[1], validate=True)
        return "SHA256:" + base64.b64encode(sha256(blob).digest()).decode().rstrip("=")
    except Exception:
        fail("invalid_input", 422)


class V2Store(AccessStore):
    def catalog_v2(self, owner, root):
        self.root(owner, root)
        return {
            "credentials": [
                public_credential(r)
                for r in self.query("access_credentials", owner, root, PUBLIC_CREDENTIAL)
                .order("created_at")
                .execute()
                .data
            ],
            "usages": self.query("access_usages", owner, root, PUBLIC_USAGE)
            .order("created_at")
            .execute()
            .data,
            "usage_grants": self.query("secret_usage_grants", owner, root, PUBLIC_USAGE_GRANT)
            .execute()
            .data,
        }

    def credential_valid(self, owner, root, value):
        resource = self.one("access_resources", owner, root, value["resource_id"])
        env = value["environment_id"]
        if resource["shared"] != (env is None):
            fail("invalid_input", 422)
        if env:
            self.one("root_environments", owner, root, env)
            if resource.get("environment_ids") and env not in resource["environment_ids"]:
                fail("invalid_input", 422)
        return value

    def create_credential(self, owner, root, value):
        self.root(owner, root)
        self.credential_valid(owner, root, value)
        return public_credential(self.insert("access_credentials", owner, root, value))

    def update_credential(self, owner, root, id, value):
        self.root(owner, root)
        old = self.one("access_credentials", owner, root, id)
        revision = value.pop("expected_revision")
        try:
            value = CredentialInstance.model_validate(
                {
                    **{
                        k: old.get(k, "" if k == "region" else None)
                        for k in CredentialInstance.model_fields
                    },
                    **value,
                }
            ).model_dump(mode="json")
        except ValueError:
            fail("invalid_input", 422)
        if old.get("legacy_binding_id"):
            fail("binding_changed", 409)
        if old["has_secret"] and any(
            old[k] != value[k] for k in ("resource_id", "environment_id", "kind", "fields")
        ):
            fail("binding_changed", 409)
        self.credential_valid(owner, root, value)
        rows = (
            self.sb.table("access_credentials")
            .update({**value, "revision": revision + 1})
            .eq("id", str(id))
            .eq("user_id", owner)
            .eq("root_folder_id", str(root))
            .eq("revision", revision)
            .is_("write_operation_id", "null")
            .execute()
            .data
        )
        if not rows:
            fail("binding_changed", 409)
        return public_credential(rows[0])

    def validate_values(self, row, values):
        required = set(row["fields"])
        if row["kind"] == "aws":
            required.discard("session_token")
        if not required <= set(values) or not set(values) <= set(row["fields"]):
            fail("invalid_input", 422)
        if row["kind"] == "aws" and any(
            any(ord(c) < 32 or ord(c) == 127 for c in v) for v in values.values()
        ):
            fail("invalid_input", 422)
        return ssh_fingerprint(values) if row["kind"] == "ssh" else None

    def write_v2(self, owner, root, id, body):
        self.root(owner, root)
        row = self.one("access_credentials", owner, root, id)
        if row.get("legacy_binding_id"):
            return self.write(owner, root, row["legacy_binding_id"], body)
        fingerprint = self.validate_values(row, body.values)
        key = os.getenv("KIOKU_VAULT_WRITE_HMAC_KEY", "")
        if len(key) < 32:
            fail("provider_unavailable", 503)
        op = str(body.idempotency_key)
        payload = {"credential_id": str(id), **body.model_dump(mode="json")}
        input_hmac = hmac.new(
            key.encode(),
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(),
            "sha256",
        ).hexdigest()
        reference = "KIOKU_" + digest(owner + ":" + str(root) + ":v2:" + op)
        params = {
            "p_id": op,
            "p_owner": owner,
            "p_root": str(root),
            "p_credential": str(id),
            "p_revision": body.expected_revision,
            "p_ref": reference,
            "p_digest": input_hmac,
            "p_expiry": body.credential_expires_at.isoformat()
            if body.credential_expires_at
            else None,
            "p_fingerprint": fingerprint,
        }
        try:
            reserved = self.sb.rpc("reserve_credential_write", params).execute().data
        except Exception:
            fail("binding_changed", 409)
        if reserved["status"] == "complete":
            return {"ok": True, "revision": body.expected_revision + 1}
        if reserved["status"] != "pending":
            fail("binding_changed", 409)
        try:
            InfisicalProvider().write(reserved["provider_ref"], body.values)
        except ProviderUnavailable:
            fail("provider_unavailable", 503)
        try:
            revision = (
                self.sb.rpc("finish_credential_write", {"p_id": op, "p_owner": owner})
                .execute()
                .data
            )
        except Exception:
            fail("binding_changed", 409)
        self.event(
            owner,
            root,
            resource_id=row["resource_id"],
            credential_id=str(id),
            action="credential_replaced",
            outcome="allowed",
        )
        return {"ok": True, "revision": revision}

    def reconcile_v2(self, owner, root, id):
        self.root(owner, root)
        row = self.one("access_credentials", owner, root, id)
        if row.get("legacy_binding_id"):
            return self.reconcile(owner, root, row["legacy_binding_id"])
        op_id = row.get("write_operation_id")
        if not op_id:
            return {"ok": True, "state": "unchanged", "revision": row["revision"]}
        op = self.one("credential_write_operations", owner, root, op_id)
        if op["credential_id"] != str(id) or op["status"] != "pending":
            fail("binding_changed", 409)
        try:
            exists = InfisicalProvider().exists(op["provider_ref"])
        except ProviderUnavailable:
            fail("provider_unavailable", 503)
        rpc = "finish_credential_write" if exists else "cancel_credential_write"
        try:
            revision = self.sb.rpc(rpc, {"p_id": op_id, "p_owner": owner}).execute().data
        except Exception:
            fail("binding_changed", 409)
        return {"ok": True, "state": "completed" if exists else "cancelled", "revision": revision}

    def usage_valid(self, owner, root, value):
        credential = self.one("access_credentials", owner, root, value["credential_id"])
        delivery = value["delivery"]
        if not usage_fields(delivery) <= set(credential["fields"]):
            fail("invalid_input", 422)
        if delivery["kind"] == "ssh" and credential["kind"] != "ssh":
            fail("invalid_input", 422)
        if credential["kind"] == "ssh" and delivery["kind"] != "ssh":
            fail("invalid_input", 422)
        if (
            delivery["kind"] == "file"
            and delivery["destination"]["name"] == "AWS_SHARED_CREDENTIALS_FILE"
            and credential["kind"] != "aws"
        ):
            fail("invalid_input", 422)
        if credential["kind"] == "aws":
            if delivery["kind"] not in {"env", "file"}:
                fail("invalid_input", 422)
            if delivery["kind"] == "env":
                mapping = delivery["field_mapping"]
                expected = {
                    "AWS_ACCESS_KEY_ID": "access_key_id",
                    "AWS_SECRET_ACCESS_KEY": "secret_access_key",
                }
                if (
                    not all(mapping.get(k) == v for k, v in expected.items())
                    or any(k not in {*expected, "AWS_SESSION_TOKEN"} for k in mapping)
                    or mapping.get("AWS_SESSION_TOKEN", "session_token") != "session_token"
                ):
                    fail("invalid_input", 422)
                delivery["clear_env"] = list(dict.fromkeys(delivery["clear_env"] + AWS_CLEAR))
            else:
                if (
                    delivery["format"] != "toml"
                    or delivery["destination"]
                    != {"kind": "env", "name": "AWS_SHARED_CREDENTIALS_FILE"}
                    or delivery["source_template"].strip() not in {"", "[default]"}
                ):
                    fail("invalid_input", 422)
                mapping = {tuple(p["path"]): p["field"] for p in delivery["patches"]}
                expected = {
                    ("default", "aws_access_key_id"): "access_key_id",
                    ("default", "aws_secret_access_key"): "secret_access_key",
                }
                if (
                    not all(mapping.get(k) == v for k, v in expected.items())
                    or any(k not in {*expected, ("default", "aws_session_token")} for k in mapping)
                    or mapping.get(("default", "aws_session_token"), "session_token")
                    != "session_token"
                ):
                    fail("invalid_input", 422)
                delivery["source_template"] = "[default]\n"
        return value

    def create_usage(self, owner, root, value):
        self.root(owner, root)
        value = self.usage_valid(owner, root, value)
        return self.insert("access_usages", owner, root, value)

    def update_usage(self, owner, root, id, value):
        self.root(owner, root)
        old = self.one("access_usages", owner, root, id)
        if old.get("legacy_binding_id"):
            fail("binding_changed", 409)
        revision = value.pop("expected_revision")
        value = self.usage_valid(owner, root, value)
        rows = (
            self.sb.table("access_usages")
            .update({**value, "revision": revision + 1})
            .eq("id", str(id))
            .eq("user_id", owner)
            .eq("root_folder_id", str(root))
            .eq("revision", revision)
            .execute()
            .data
        )
        if not rows:
            fail("binding_changed", 409)
        return rows[0]

    def grant_usage(self, owner, root, value):
        self.root(owner, root)
        device = self.one("secret_devices", owner, root, value["device_id"])
        if device["revoked_at"] or expired(device["expires_at"]):
            fail("device_revoked", 409)
        usage = self.one("access_usages", owner, root, value["usage_id"])
        expected_revision = value.pop("expected_usage_revision")
        if usage["revision"] != expected_revision:
            fail("binding_changed", 409)
        fields = usage_fields(usage["delivery"])
        caps = usage_capabilities(usage["delivery"])
        # An exact recipe snapshot is the destination constraint; no wildcard grants.
        if fields != set(value["allowed_fields"]) or caps != set(value["capabilities"]):
            fail("invalid_input", 422)
        try:
            row = (
                self.sb.rpc(
                    "grant_secret_usage",
                    {
                        "p_id": str(uuid4()),
                        "p_owner": owner,
                        "p_root": str(root),
                        "p_device": value["device_id"],
                        "p_usage": value["usage_id"],
                        "p_revision": expected_revision,
                        "p_fields": value["allowed_fields"],
                        "p_capabilities": value["capabilities"],
                        "p_expiry": value.get("expires_at"),
                    },
                )
                .execute()
                .data
            )
        except Exception:
            fail("binding_changed", 409)
        return {k: row.get(k) for k in PUBLIC_USAGE_GRANT.split(",")}

    def revoke_usage(self, owner, root, grant):
        self.root(owner, root)
        self.one("secret_usage_grants", owner, root, grant)
        try:
            self.sb.rpc(
                "revoke_secret_usage", {"p_id": str(grant), "p_owner": owner, "p_root": str(root)}
            ).execute()
        except Exception:
            fail("binding_changed", 409)
        return {"ok": True}

    def authorize_usage(self, owner, root, device, requested, allow_raw):
        usage = self.one("access_usages", owner, root, requested.usage_id)
        credential = self.one("access_credentials", owner, root, usage["credential_id"])
        grants = (
            self.query("secret_usage_grants", owner, root)
            .eq("device_id", device["id"])
            .eq("usage_id", usage["id"])
            .limit(1)
            .execute()
            .data
        )
        if not grants or grants[0]["revoked_at"] or expired(grants[0]["expires_at"]):
            fail("access_denied", 403)
        grant = grants[0]
        if (
            grant["usage_revision"] != usage["revision"]
            or not usage_fields(usage["delivery"]) <= set(grant["allowed_fields"])
            or not usage_capabilities(usage["delivery"]) <= set(grant["capabilities"])
        ):
            fail("access_denied", 403)
        if "raw_secret_argv" in usage_capabilities(usage["delivery"]) and not allow_raw:
            fail("access_denied", 403)
        if (
            usage["revision"] != requested.revision
            or credential["revision"] != requested.credential_revision
            or not usage["enabled"]
            or not credential["enabled"]
            or credential.get("write_operation_id")
        ):
            fail("binding_changed", 409)
        if not credential["has_secret"] or not credential["provider_ref"]:
            fail("secret_unavailable", 409)
        if expired(credential["credential_expires_at"], 60):
            fail("credential_expired", 409)
        # Revalidate structured persisted metadata, including legacy recipes.
        Usage.model_validate(
            {k: usage[k] for k in ("credential_id", "name", "consumer", "delivery", "enabled")}
        )
        self.usage_valid(owner, root, {k: usage[k] for k in ("credential_id", "delivery")})
        self.credential_valid(owner, root, credential)
        if usage.get("legacy_binding_id"):
            legacy = self.one("access_bindings", owner, root, usage["legacy_binding_id"])
            if legacy["revision"] != credential["revision"] or legacy.get("write_operation_id"):
                fail("binding_changed", 409)
            self.binding(owner, root, legacy)
            usage["delivery"]["clear_env"] = legacy["clear_env"]
        return usage, credential

    def resolve_v2(self, token, body):
        device = self.device(token, body.root_id)
        owner, root = device["user_id"], body.root_id
        selected = [
            self.authorize_usage(owner, root, device, req, body.allow_raw_secret_argv)
            for req in body.usages
        ]
        # Detect all metadata destination conflicts before the first provider read.
        env_names, arg_flags, ssh_count, aws_count = set(), set(), 0, 0
        for usage, credential in selected:
            d = usage["delivery"]
            aws_count += credential["kind"] == "aws"
            names = (
                set(d["field_mapping"])
                if d["kind"] == "env"
                else {d["destination"]["name"]}
                if d["kind"] == "file" and d["destination"]["kind"] == "env"
                else set()
            )
            if env_names & names:
                fail("invalid_input", 422)
            env_names |= names
            if d["kind"] == "file" and d["destination"]["kind"] == "arg":
                if d["destination"]["name"] in arg_flags:
                    fail("invalid_input", 422)
                arg_flags.add(d["destination"]["name"])
            ssh_count += d["kind"] == "ssh"
        if ssh_count > 1 or aws_count > 1:
            fail("invalid_input", 422)
        provider, bundles = InfisicalProvider(), {}
        for _, credential in selected:
            if credential["id"] not in bundles:
                try:
                    bundles[credential["id"]] = provider.read(credential["provider_ref"])
                except ProviderUnavailable:
                    fail("provider_unavailable", 503)
                self.validate_values(credential, bundles[credential["id"]])
        # Final authorization after all I/O, never return partial descriptors.
        self.device(token, root)
        fresh = [
            self.authorize_usage(owner, root, device, req, body.allow_raw_secret_argv)
            for req in body.usages
        ]
        for previous, current in zip(selected, fresh, strict=True):
            if previous != current:
                fail("binding_changed", 409)
        deliveries, clear, expiry = [], [], []
        for usage, credential in selected:
            values, d = bundles[credential["id"]], usage["delivery"]
            out = {
                "usage_id": usage["id"],
                "revision": usage["revision"],
                "credential_id": credential["id"],
                "credential_revision": credential["revision"],
                "kind": d["kind"],
            }
            if d["kind"] == "env":
                result = {}
                for dest, field in d["field_mapping"].items():
                    if field not in values:
                        if credential["kind"] == "aws" and field == "session_token":
                            continue
                        fail("secret_unavailable", 409)
                    result[dest] = values[field]
                resource = self.one("access_resources", owner, root, credential["resource_id"])
                legacy_cloud = credential.get("legacy_binding_id") and resource["type"] == "cloud"
                region = credential.get("region") or (
                    resource.get("region") if legacy_cloud else ""
                )
                if (credential["kind"] == "aws" or legacy_cloud) and region:
                    if "AWS_REGION" in env_names:
                        fail("invalid_input", 422)
                    result["AWS_REGION"] = region
                out["environment"] = result
                clear.extend(d["clear_env"])
            elif d["kind"] == "argv":
                out["arguments"] = [
                    {
                        "kind": "literal" if a["kind"] == "literal" else "secret",
                        "value": a["value"] if a["kind"] == "literal" else values[a["field"]],
                    }
                    for a in d["arguments"]
                ]
            elif d["kind"] == "file":
                out.update({k: d[k] for k in ("format", "source_template", "destination")})
                out["patches"] = [
                    {"path": p["path"], "value": values[p["field"]]}
                    for p in d["patches"]
                    if p["field"] in values
                ]
                if credential["kind"] == "aws":
                    clear.extend(AWS_CLEAR)
                    resource = self.one("access_resources", owner, root, credential["resource_id"])
                    out["environment"] = (
                        {"AWS_REGION": credential["region"]} if credential.get("region") else {}
                    )
            elif d["kind"] == "ssh":
                out.update({k: d[k] for k in ("host", "user", "port", "host_key")})
                out["private_key"] = values[d["private_key_field"]]
                if d.get("passphrase_field"):
                    out["passphrase"] = values[d["passphrase_field"]]
            deliveries.append(out)
            if credential["credential_expires_at"]:
                expiry.append(credential["credential_expires_at"])
        for usage, credential in selected:
            self.event(
                owner,
                root,
                device_id=device["id"],
                credential_id=credential["id"],
                usage_id=usage["id"],
                resource_id=credential["resource_id"],
                invocation_id=str(body.invocation_id),
                action="resolve_v2",
                outcome="allowed",
            )
        self.sb.table("secret_devices").update({"last_used_at": now().isoformat()}).eq(
            "id", device["id"]
        ).eq("user_id", owner).eq("root_folder_id", str(root)).execute()
        return {
            "invocation_id": str(body.invocation_id),
            "deliveries": deliveries,
            "clear_env": list(dict.fromkeys(clear)),
            "credential_expires_at": min(expiry) if expiry else None,
        }
