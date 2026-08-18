"""API key management endpoints for MCP authentication."""

import hashlib
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from db.client import get_supabase
from routes._validation import require_uuid
from services.scope import validate_scope_folder

router = APIRouter(prefix="/api/api-keys")


class CreateKeyRequest(BaseModel):
    name: str = "Default"
    scope_folder_id: str


class ApiKeyResponse(BaseModel):
    id: str
    name: str
    scope_folder_id: str
    scope_folder_name: str
    created_at: str


class CreateKeyResponse(BaseModel):
    key: str
    id: str
    name: str
    scope_folder_id: str
    scope_folder_name: str
    created_at: str


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@router.get("")
async def list_api_keys(
    user_id: str = Depends(get_current_user),
) -> list[ApiKeyResponse]:
    """List all API keys for the user."""
    sb = get_supabase()
    result = (
        sb.table("api_keys")
        .select("id, name, scope_folder_id, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    keys = []
    for row in result.data:
        if not row.get("scope_folder_id"):
            continue
        folder_name = "Unknown"
        # Defensive user_id filter: audit found this lookup relied entirely on
        # the api_keys row already being user-scoped, which is true today but
        # fragile — any future refactor removing that guard would leak a
        # folder name across users.
        folder = (
            sb.table("folders")
            .select("name")
            .eq("id", row["scope_folder_id"])
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if folder.data:
            folder_name = folder.data[0]["name"]
        keys.append(
            ApiKeyResponse(
                id=row["id"],
                name=row["name"],
                scope_folder_id=row["scope_folder_id"],
                scope_folder_name=folder_name,
                created_at=row["created_at"],
            )
        )
    return keys


@router.post("")
async def create_api_key(
    body: CreateKeyRequest,
    user_id: str = Depends(get_current_user),
) -> CreateKeyResponse:
    """Generate a new API key scoped to a root folder. Replaces existing key for same scope."""
    sb = get_supabase()
    validate_scope_folder(body.scope_folder_id, user_id)

    sb.table("api_keys").delete().eq("user_id", user_id).eq(
        "scope_folder_id", body.scope_folder_id
    ).execute()

    raw_key = f"rag_{secrets.token_hex(32)}"
    key_hash = _hash_key(raw_key)

    result = (
        sb.table("api_keys")
        .insert(
            {
                "user_id": user_id,
                "key_hash": key_hash,
                "name": body.name.strip() or "Default",
                "scope_folder_id": body.scope_folder_id,
            }
        )
        .execute()
    )

    row = result.data[0]
    # Defensive user_id filter (see comment on the list endpoint).
    folder = (
        sb.table("folders")
        .select("name")
        .eq("id", body.scope_folder_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    folder_name = folder.data[0]["name"] if folder.data else "Unknown"

    return CreateKeyResponse(
        key=raw_key,
        id=row["id"],
        name=row["name"],
        scope_folder_id=row["scope_folder_id"],
        scope_folder_name=folder_name,
        created_at=row["created_at"],
    )


@router.delete("/{key_id}")
async def revoke_api_key(
    key_id: str,
    user_id: str = Depends(get_current_user),
):
    """Revoke a specific API key by ID."""
    require_uuid(key_id, "API key not found")
    sb = get_supabase()
    result = sb.table("api_keys").delete().eq("id", key_id).eq("user_id", user_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="API key not found")
    return {"ok": True}
