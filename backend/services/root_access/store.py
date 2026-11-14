"""Owner/root scoped access operations. No credential values in DB or audit."""

import hmac
import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

from fastapi import HTTPException

from services.root_access.provider import InfisicalProvider, ProviderUnavailable

PUBLIC_BINDING = (
    "id,resource_id,environment_id,consumer,field_mapping,clear_env,revision,"
    "enabled,has_secret,credential_expires_at,write_operation_id"
)
PUBLIC_DEVICE = "id,label,created_at,last_used_at,expires_at,revoked_at"


def fail(code, status=400):
    messages = {
        "access_denied": "Access denied.",
        "binding_changed": "This mapping changed. Refresh and try again.",
        "provider_unavailable": "The credential vault is unavailable. Try again shortly.",
        "invalid_input": "Check the supplied fields.",
        "credential_expired": "The credential has expired or expires too soon.",
        "secret_unavailable": "No usable credential is stored for this mapping.",
        "device_revoked": "This computer is revoked or its enrollment expired.",
        "enrollment_expired": "The enrollment request has expired.",
        "authentication_required": "Enroll this computer before requesting credentials.",
    }
    raise HTTPException(
        status_code=status,
        detail={"code": code, "message": messages.get(code, "Request could not be completed.")},
        headers={"Cache-Control": "no-store"},
    )


def now():
    return datetime.now(timezone.utc)


def expired(value, margin=0):
    if not value:
        return False
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) <= now() + timedelta(
            seconds=margin
        )
    except (ValueError, TypeError):
        return True


def digest(value):
    return sha256(value.encode()).hexdigest()


class AccessStore:
    def __init__(self, sb):
        self.sb = sb

    def root(self, owner, root):
        rows = (
            self.sb.table("folders")
            .select("id,parent_id")
            .eq("id", str(root))
            .eq("user_id", owner)
            .limit(1)
            .execute()
            .data
        )
        if not rows or rows[0]["parent_id"] is not None:
            fail("access_denied", 404)

    def query(self, table, owner, root, columns="*"):
        return (
            self.sb.table(table)
            .select(columns)
            .eq("user_id", owner)
            .eq("root_folder_id", str(root))
        )

    def one(self, table, owner, root, id, columns="*"):
        rows = self.query(table, owner, root, columns).eq("id", str(id)).limit(1).execute().data
        if not rows:
            fail("access_denied", 404)
        return rows[0]

    @staticmethod
    def public_binding(row):
        result = {
            key: row.get(key) for key in PUBLIC_BINDING.split(",") if key != "write_operation_id"
        }
        result["pending_operation_id"] = row.get("write_operation_id")
        return result

    def catalog(self, owner, root):
        self.root(owner, root)
        guide = (
            self.query("root_access_guides", owner, root, "markdown,revision")
            .limit(1)
            .execute()
            .data
        )
        try:
            configured = InfisicalProvider().configured
        except ProviderUnavailable:
            configured = False
        return {
            "root_id": str(root),
            "guide": guide[0] if guide else {"markdown": "", "revision": 0},
            "environments": self.query("root_environments", owner, root, "id,name,slug,sensitivity")
            .order("name")
            .execute()
            .data,
            "resources": self.query(
                "access_resources",
                owner,
                root,
                "id,name,description,type,aliases,shared,account,region",
            )
            .order("name")
            .execute()
            .data,
            "bindings": [
                self.public_binding(row)
                for row in self.query("access_bindings", owner, root, PUBLIC_BINDING).execute().data
            ],
            "devices": self.query("secret_devices", owner, root, PUBLIC_DEVICE).execute().data,
            "grants": self.query(
                "secret_grants", owner, root, "id,device_id,binding_id,expires_at,revoked_at"
            )
            .execute()
            .data,
            "activity": self.query(
                "secret_access_events",
                owner,
                root,
                "id,device_id,resource_id,binding_id,action,outcome,created_at",
            )
            .order("created_at", desc=True)
            .limit(100)
            .execute()
            .data,
            "provider": {"configured": configured},
        }

    def insert(self, table, owner, root, value):
        self.root(owner, root)
        return (
            self.sb.table(table)
            .insert({**value, "user_id": owner, "root_folder_id": str(root)})
            .execute()
            .data[0]
        )

    def binding(self, owner, root, value):
        resource = self.one("access_resources", owner, root, value["resource_id"])
        if (
            resource["shared"]
            and value["environment_id"] is not None
            or not resource["shared"]
            and value["environment_id"] is None
        ):
            fail("invalid_input", 422)
        if value["environment_id"]:
            self.one("root_environments", owner, root, value["environment_id"])
        if resource["type"] == "cloud":
            # SDK default-chain isolation recipe is explicitly supported for AWS.
            if (
                "AWS_ACCESS_KEY_ID" not in value["field_mapping"]
                or "AWS_SECRET_ACCESS_KEY" not in value["field_mapping"]
            ):
                fail("invalid_input", 422)
            value["clear_env"] = list(
                dict.fromkeys(
                    value["clear_env"]
                    + [
                        "AWS_ACCESS_KEY_ID",
                        "AWS_SECRET_ACCESS_KEY",
                        "AWS_SESSION_TOKEN",
                        "AWS_PROFILE",
                        "AWS_DEFAULT_PROFILE",
                        "AWS_SHARED_CREDENTIALS_FILE",
                        "AWS_CONFIG_FILE",
                        "AWS_WEB_IDENTITY_TOKEN_FILE",
                        "AWS_ROLE_ARN",
                        "AWS_ROLE_SESSION_NAME",
                        "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
                        "AWS_CONTAINER_CREDENTIALS_FULL_URI",
                        "AWS_CONTAINER_AUTHORIZATION_TOKEN",
                        "AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE",
                    ]
                )
            )
        mongo_names = {"MONGO_URI", "MONGODB_URI", "MONGO_URL", "MONGODB_URL", "MONGO_DB_URL"}
        if mongo_names & set(value["field_mapping"]):
            value["clear_env"] = list(dict.fromkeys(value["clear_env"] + sorted(mongo_names)))
        if len(value["clear_env"]) > 32:
            fail("invalid_input", 422)
        return value

    def event(self, owner, root, **data):
        self.sb.table("secret_access_events").insert(
            {"user_id": owner, "root_folder_id": str(root), **data}
        ).execute()

    def write(self, owner, root, binding, body):
        self.root(owner, root)
        row = self.one("access_bindings", owner, root, binding)
        if set(body.values) != set(row["field_mapping"].values()):
            fail("invalid_input", 422)
        op = str(body.idempotency_key)
        hmac_key = os.getenv("KIOKU_VAULT_WRITE_HMAC_KEY", "")
        if len(hmac_key) < 32:
            fail("provider_unavailable", 503)
        input_hmac = hmac.new(
            hmac_key.encode(),
            json.dumps(
                body.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode(),
            "sha256",
        ).hexdigest()
        reference = "KIOKU_" + digest(owner + ":" + str(root) + ":" + op)
        try:
            reserved = (
                self.sb.rpc(
                    "reserve_secret_write",
                    {
                        "p_id": op,
                        "p_owner": owner,
                        "p_root": str(root),
                        "p_binding": str(binding),
                        "p_revision": body.expected_revision,
                        "p_ref": reference,
                        "p_digest": input_hmac,
                        "p_expiry": body.credential_expires_at.isoformat()
                        if body.credential_expires_at
                        else None,
                    },
                )
                .execute()
                .data
            )
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
                self.sb.rpc(
                    "finish_secret_write",
                    {
                        "p_id": op,
                        "p_owner": owner,
                        "p_expiry": body.credential_expires_at.isoformat()
                        if body.credential_expires_at
                        else None,
                    },
                )
                .execute()
                .data
            )
        except Exception:
            fail("binding_changed", 409)
        self.event(
            owner,
            root,
            binding_id=str(binding),
            resource_id=row["resource_id"],
            action="credential_replaced",
            outcome="allowed",
        )
        return {"ok": True, "revision": revision}

    def reconcile(self, owner, root, binding):
        self.root(owner, root)
        row = self.one("access_bindings", owner, root, binding)
        op_id = row.get("write_operation_id")
        if not op_id:
            return {"ok": True, "state": "unchanged", "revision": row["revision"]}
        op = self.one("secret_write_operations", owner, root, op_id)
        if op["binding_id"] != str(binding) or op["status"] != "pending":
            fail("binding_changed", 409)
        try:
            exists = InfisicalProvider().exists(op["provider_ref"])
        except ProviderUnavailable:
            fail("provider_unavailable", 503)
        if exists:
            revision = (
                self.sb.rpc(
                    "finish_secret_write",
                    {"p_id": op_id, "p_owner": owner, "p_expiry": op.get("credential_expires_at")},
                )
                .execute()
                .data
            )
            return {"ok": True, "state": "completed", "revision": revision}
        revision = (
            self.sb.rpc("cancel_secret_write", {"p_id": op_id, "p_owner": owner}).execute().data
        )
        return {"ok": True, "state": "cancelled", "revision": revision}

    def enroll(self, owner, root, label):
        self.root(owner, root)
        code = secrets.token_urlsafe(40)
        rows = (
            self.query("secret_access_enrollments", owner, root, "id")
            .eq("status", "pending")
            .gt("expires_at", now().isoformat())
            .limit(11)
            .execute()
            .data
        )
        if len(rows) >= 10:
            fail("invalid_input", 429)
        row = self.insert(
            "secret_access_enrollments",
            owner,
            root,
            {
                "label": label,
                "code_hash": digest(code),
                "expires_at": (now() + timedelta(minutes=10)).isoformat(),
            },
        )
        return {
            "request_id": row["id"],
            "device_code": code,
            "expires_at": row["expires_at"],
            "interval": 2,
            "verification_url": os.getenv("FRONTEND_URL", "https://kioku.merigafy.com").rstrip("/")
            + "/folders/"
            + str(root)
            + "/access?request_id="
            + row["id"],
        }

    def enrollment(self, owner, root, request):
        self.root(owner, root)
        row = self.one("secret_access_enrollments", owner, root, request)
        if expired(row["expires_at"]):
            fail("enrollment_expired", 410)
        return row

    def poll(self, request, code):
        token = "ksd_" + secrets.token_urlsafe(40)
        try:
            result = (
                self.sb.rpc(
                    "consume_secret_enrollment",
                    {
                        "p_request": str(request),
                        "p_code_hash": digest(code),
                        "p_device": str(uuid4()),
                        "p_credential_hash": digest(token),
                    },
                )
                .execute()
                .data
            )
        except Exception:
            fail("access_denied", 403)
        if result["status"] == "approved":
            return {**result, "device_token": token}
        if result["status"] == "pending":
            return {"status": "pending"}
        if result["status"] == "expired":
            fail("enrollment_expired", 410)
        fail("access_denied", 403)

    def device(self, token, root):
        if not token.startswith("ksd_") or len(token) > 200:
            fail("authentication_required", 401)
        rows = (
            self.sb.table("secret_devices")
            .select("*")
            .eq("credential_hash", digest(token))
            .eq("root_folder_id", str(root))
            .limit(1)
            .execute()
            .data
        )
        if not rows:
            fail("authentication_required", 401)
        device = rows[0]
        if device["revoked_at"] or expired(device["expires_at"]):
            fail("device_revoked", 403)
        self.root(device["user_id"], root)
        return device

    def resolve(self, token, body):
        device = self.device(token, body.root_id)
        owner = device["user_id"]
        root = body.root_id
        bindings = []
        environment = {}
        clear = []
        expiry = []
        for requested in body.bindings:
            row = self.one("access_bindings", owner, root, requested.binding_id)
            grant = (
                self.query("secret_grants", owner, root)
                .eq("device_id", device["id"])
                .eq("binding_id", row["id"])
                .limit(1)
                .execute()
                .data
            )
            if not grant or grant[0]["revoked_at"] or expired(grant[0]["expires_at"]):
                self.event(
                    owner,
                    root,
                    device_id=device["id"],
                    binding_id=row["id"],
                    resource_id=row["resource_id"],
                    invocation_id=str(body.invocation_id),
                    action="resolve",
                    outcome="denied",
                )
                fail("access_denied", 403)
            if (
                not row["enabled"]
                or row["revision"] != requested.revision
                or row["write_operation_id"]
            ):
                fail("binding_changed", 409)
            if not row["has_secret"] or not row["provider_ref"]:
                fail("secret_unavailable", 409)
            if expired(row["credential_expires_at"], 60):
                fail("credential_expired", 409)
            resource = self.one("access_resources", owner, root, row["resource_id"])
            self.binding(owner, root, row)
            if set(environment) & set(row["field_mapping"]):
                fail("invalid_input", 422)
            environment.update(dict.fromkeys(row["field_mapping"]))
            clear.extend(row["clear_env"])
            if resource["type"] == "cloud" and resource.get("region"):
                environment.setdefault("AWS_REGION", resource["region"])
            if row["credential_expires_at"]:
                expiry.append(row["credential_expires_at"])
            bindings.append(row)
        provider = InfisicalProvider()
        for row in bindings:
            try:
                values = provider.read(row["provider_ref"])
            except ProviderUnavailable:
                fail("provider_unavailable", 503)
            for dest, field in row["field_mapping"].items():
                if field not in values:
                    fail("secret_unavailable", 409)
                environment[dest] = values[field]
        # Recheck mutable authorization/mappings after provider I/O, before delivery.
        self.device(token, root)
        for row in bindings:
            fresh = self.one("access_bindings", owner, root, row["id"])
            grants = (
                self.query("secret_grants", owner, root)
                .eq("device_id", device["id"])
                .eq("binding_id", row["id"])
                .limit(1)
                .execute()
                .data
            )
            if not grants or grants[0]["revoked_at"] or expired(grants[0]["expires_at"]):
                fail("access_denied", 403)
            if (
                fresh["revision"] != row["revision"]
                or fresh["write_operation_id"]
                or not fresh["enabled"]
            ):
                fail("binding_changed", 409)
            if expired(fresh["credential_expires_at"], 60):
                fail("credential_expired", 409)
            self.event(
                owner,
                root,
                device_id=device["id"],
                resource_id=row["resource_id"],
                binding_id=row["id"],
                invocation_id=str(body.invocation_id),
                action="resolve",
                outcome="allowed",
            )
        self.sb.table("secret_devices").update({"last_used_at": now().isoformat()}).eq(
            "id", device["id"]
        ).eq("user_id", owner).execute()
        return {
            "invocation_id": str(body.invocation_id),
            "environment": environment,
            "clear_env": list(dict.fromkeys(clear)),
            "credential_expires_at": min(expiry) if expiry else None,
        }
