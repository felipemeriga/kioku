"""Root environment catalog and write-only credential management."""

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from auth import get_current_user
from db.client import get_supabase_thread_safe as get_supabase
from services.root_access.models import (
    Approval,
    Binding,
    BindingUpdate,
    Credential,
    Enrollment,
    Environment,
    Grant,
    Guide,
    Poll,
    Resolve,
    Resource,
)
from services.root_access.store import PUBLIC_DEVICE, AccessStore, fail, now


class SecretSafeRoute(APIRoute):
    """Never let submitted values enter validation responses or global trace logs."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe(request):
            try:
                length = request.headers.get("content-length")
                if length and int(length) > 400000:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "detail": {"code": "invalid_input", "message": "Request is too large."}
                        },
                        headers={"Cache-Control": "no-store"},
                    )
                # Bound chunked requests too, before Pydantic ever sees the body.
                if request.method in {"POST", "PUT", "PATCH"}:
                    parts = []
                    size = 0
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > 400000:
                            fail("invalid_input", 413)
                        parts.append(chunk)
                    request._body = b"".join(parts)
                response = await handler(request)
                response.headers["Cache-Control"] = "no-store"
                return response
            except RequestValidationError:
                return JSONResponse(
                    status_code=422,
                    content={
                        "detail": {"code": "invalid_input", "message": "Check the supplied fields."}
                    },
                    headers={"Cache-Control": "no-store"},
                )
            except HTTPException:
                raise
            except Exception:
                # Provider/db exceptions may contain values: never serialize/log exception.
                return JSONResponse(
                    status_code=503,
                    content={
                        "detail": {
                            "code": "provider_unavailable",
                            "message": "Access service is unavailable. Try again shortly.",
                        }
                    },
                    headers={"Cache-Control": "no-store"},
                )

        return safe


router = APIRouter(prefix="/api/root-access", route_class=SecretSafeRoute)
secret_router = APIRouter(prefix="/api/secret-access", route_class=SecretSafeRoute)


def store():
    return AccessStore(get_supabase())


def dump(body):
    return json.loads(body.model_dump_json())


@router.get("/{root_id}")
def catalog(root_id: UUID, user_id: str = Depends(get_current_user)):
    return store().catalog(user_id, root_id)


@router.put("/{root_id}/guide")
def save_guide(root_id: UUID, body: Guide, user_id: str = Depends(get_current_user)):
    s = store()
    s.root(user_id, root_id)
    try:
        revision = (
            s.sb.rpc(
                "save_root_access_guide",
                {
                    "p_owner": user_id,
                    "p_root": str(root_id),
                    "p_revision": body.expected_revision,
                    "p_markdown": body.markdown,
                },
            )
            .execute()
            .data
        )
    except Exception:
        fail("binding_changed", 409)
    return {"markdown": body.markdown, "revision": revision}


@router.get("/{root_id}/guide/revisions")
def guide_revisions(root_id: UUID, user_id: str = Depends(get_current_user)):
    s = store()
    s.root(user_id, root_id)
    return (
        s.query("root_access_guide_revisions", user_id, root_id, "revision,markdown,created_at")
        .order("revision", desc=True)
        .limit(50)
        .execute()
        .data
    )


@router.post("/{root_id}/environments")
def create_environment(root_id: UUID, body: Environment, user_id: str = Depends(get_current_user)):
    return store().insert("root_environments", user_id, root_id, dump(body))


@router.patch("/{root_id}/environments/{environment_id}")
def edit_environment(
    root_id: UUID, environment_id: UUID, body: Environment, user_id: str = Depends(get_current_user)
):
    s = store()
    s.root(user_id, root_id)
    s.one("root_environments", user_id, root_id, environment_id)
    return (
        s.sb.table("root_environments")
        .update(dump(body))
        .eq("id", str(environment_id))
        .eq("user_id", user_id)
        .eq("root_folder_id", str(root_id))
        .execute()
        .data[0]
    )


@router.post("/{root_id}/resources")
def create_resource(root_id: UUID, body: Resource, user_id: str = Depends(get_current_user)):
    return store().insert("access_resources", user_id, root_id, dump(body))


@router.patch("/{root_id}/resources/{resource_id}")
def edit_resource(
    root_id: UUID, resource_id: UUID, body: Resource, user_id: str = Depends(get_current_user)
):
    s = store()
    s.root(user_id, root_id)
    old = s.one("access_resources", user_id, root_id, resource_id)
    if (
        old["shared"] != body.shared
        and s.query("access_bindings", user_id, root_id, "id")
        .eq("resource_id", str(resource_id))
        .limit(1)
        .execute()
        .data
    ):
        fail("binding_changed", 409)
    return (
        s.sb.table("access_resources")
        .update(dump(body))
        .eq("id", str(resource_id))
        .eq("user_id", user_id)
        .eq("root_folder_id", str(root_id))
        .execute()
        .data[0]
    )


@router.post("/{root_id}/bindings")
def create_binding(root_id: UUID, body: Binding, user_id: str = Depends(get_current_user)):
    s = store()
    s.root(user_id, root_id)
    value = s.binding(user_id, root_id, dump(body))
    row = s.insert("access_bindings", user_id, root_id, value)
    return s.public_binding(row)


@router.patch("/{root_id}/bindings/{binding_id}")
def edit_binding(
    root_id: UUID, binding_id: UUID, body: BindingUpdate, user_id: str = Depends(get_current_user)
):
    s = store()
    s.root(user_id, root_id)
    old = s.one("access_bindings", user_id, root_id, binding_id)
    value = dump(body)
    revision = value.pop("expected_revision")
    if old["resource_id"] != str(body.resource_id) or old["environment_id"] != (
        str(body.environment_id) if body.environment_id else None
    ):
        fail("binding_changed", 409)
    value = s.binding(user_id, root_id, value)
    # Once a credential exists, changing field names requires a replacement first.
    if old["has_secret"] and set(value["field_mapping"].values()) != set(
        old["field_mapping"].values()
    ):
        fail("binding_changed", 409)
    rows = (
        s.sb.table("access_bindings")
        .update({**value, "revision": revision + 1})
        .eq("id", str(binding_id))
        .eq("user_id", user_id)
        .eq("root_folder_id", str(root_id))
        .eq("revision", revision)
        .is_("write_operation_id", "null")
        .execute()
        .data
    )
    if not rows:
        fail("binding_changed", 409)
    return s.public_binding(rows[0])


@router.post("/{root_id}/bindings/{binding_id}/credential")
def replace_credential(
    root_id: UUID, binding_id: UUID, body: Credential, user_id: str = Depends(get_current_user)
):
    return store().write(user_id, root_id, binding_id, body)


@router.post("/{root_id}/bindings/{binding_id}/credential/reconcile")
def reconcile_credential(root_id: UUID, binding_id: UUID, user_id: str = Depends(get_current_user)):
    return store().reconcile(user_id, root_id, binding_id)


@router.post("/{root_id}/grants")
def grant(root_id: UUID, body: Grant, user_id: str = Depends(get_current_user)):
    s = store()
    s.root(user_id, root_id)
    device = s.one("secret_devices", user_id, root_id, body.device_id)
    if device["revoked_at"]:
        fail("device_revoked", 409)
    s.one("access_bindings", user_id, root_id, body.binding_id)
    value = {"user_id": user_id, "root_folder_id": str(root_id), **dump(body), "revoked_at": None}
    rows = (
        s.sb.table("secret_grants").upsert(value, on_conflict="device_id,binding_id").execute().data
    )
    return {
        k: rows[0].get(k) for k in ("id", "device_id", "binding_id", "expires_at", "revoked_at")
    }


@router.delete("/{root_id}/grants/{grant_id}")
def revoke_grant(root_id: UUID, grant_id: UUID, user_id: str = Depends(get_current_user)):
    s = store()
    s.root(user_id, root_id)
    s.one("secret_grants", user_id, root_id, grant_id)
    s.sb.table("secret_grants").update({"revoked_at": now().isoformat()}).eq(
        "id", str(grant_id)
    ).eq("user_id", user_id).eq("root_folder_id", str(root_id)).execute()
    return {"ok": True}


@router.post("/{root_id}/devices/{device_id}/revoke")
def revoke_device(root_id: UUID, device_id: UUID, user_id: str = Depends(get_current_user)):
    s = store()
    s.root(user_id, root_id)
    s.one("secret_devices", user_id, root_id, device_id)
    rows = (
        s.sb.table("secret_devices")
        .update({"revoked_at": now().isoformat()})
        .eq("id", str(device_id))
        .eq("user_id", user_id)
        .eq("root_folder_id", str(root_id))
        .execute()
        .data
    )
    return {k: rows[0].get(k) for k in PUBLIC_DEVICE.split(",")}


@router.get("/{root_id}/enrollments/{request_id}")
def enrollment(root_id: UUID, request_id: UUID, user_id: str = Depends(get_current_user)):
    row = store().enrollment(user_id, root_id, request_id)
    return {k: row[k] for k in ("id", "label", "expires_at", "status")}


@router.post("/{root_id}/enrollments/{request_id}/approve")
def approve(
    root_id: UUID, request_id: UUID, body: Approval, user_id: str = Depends(get_current_user)
):
    s = store()
    row = s.enrollment(user_id, root_id, request_id)
    if row["status"] != "pending":
        fail("binding_changed", 409)
    for binding_id in body.binding_ids:
        s.one("access_bindings", user_id, root_id, binding_id)
    rows = (
        s.sb.table("secret_access_enrollments")
        .update(
            {"status": "approved", "binding_ids": [str(i) for i in dict.fromkeys(body.binding_ids)]}
        )
        .eq("id", str(request_id))
        .eq("user_id", user_id)
        .eq("root_folder_id", str(root_id))
        .eq("status", "pending")
        .execute()
        .data
    )
    if not rows:
        fail("binding_changed", 409)
    return {"ok": True}


@router.post("/{root_id}/enrollments/{request_id}/deny")
def deny(root_id: UUID, request_id: UUID, user_id: str = Depends(get_current_user)):
    s = store()
    s.enrollment(user_id, root_id, request_id)
    rows = (
        s.sb.table("secret_access_enrollments")
        .update({"status": "denied"})
        .eq("id", str(request_id))
        .eq("user_id", user_id)
        .eq("root_folder_id", str(root_id))
        .eq("status", "pending")
        .execute()
        .data
    )
    if not rows:
        fail("binding_changed", 409)
    return {"ok": True}


@secret_router.post("/enroll")
def start_enrollment(body: Enrollment, user_id: str = Depends(get_current_user)):
    return store().enroll(user_id, body.root_id, body.label)


@secret_router.post("/enroll/poll")
def poll_enrollment(body: Poll):
    return store().poll(body.request_id, body.device_code)


@secret_router.post("/resolve")
def resolve(body: Resolve, request: Request, response: Response):
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        fail("authentication_required", 401)
    response.headers["Cache-Control"] = "no-store"
    return store().resolve(authorization[7:], body)
