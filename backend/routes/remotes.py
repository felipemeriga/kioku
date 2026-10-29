"""Manabi machine registration and outbound connection presence (no memory capture)."""

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

import anyio
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from auth import get_current_user
from db.client import get_supabase_thread_safe

router = APIRouter(prefix="/api/remotes", tags=["remotes"])
log = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 30
STALE_SECONDS = 90
PUBLIC_COLUMNS = (
    "id,name,custom_name,platform,version,created_at,connected_at,last_seen,connected,"
    "os_name,os_id,architecture,inventory,inventory_updated_at,warnings"
)


class Registration(BaseModel):
    id: UUID
    secret: str = Field(pattern=r"^[a-f0-9]{64}$")
    name: str = Field(min_length=1, max_length=120)
    platform: str = Field(min_length=1, max_length=60)
    version: str = Field(min_length=1, max_length=40)


class RepoInventory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-f0-9]{64}$")
    folder_id: UUID
    name: str = Field(min_length=1, max_length=120)
    path: str = Field(min_length=1, max_length=1024, pattern=r"^[^\x00-\x1f\x7f]+$")
    agents: list[Literal["claude", "codex"]] = Field(min_length=1, max_length=2)
    initialized_at: datetime
    available: bool


class InventoryWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: Literal["repo_unavailable", "registry_unreadable"]
    observed_at: datetime


class MachineInventory(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    os_name: str = Field(min_length=1, max_length=60)
    os_id: str = Field(pattern=r"^[a-z0-9_-]{1,30}$")
    architecture: str = Field(pattern=r"^[a-z0-9_-]{1,30}$")
    repositories: list[RepoInventory] = Field(max_length=200)
    warnings: list[InventoryWarning] = Field(max_length=2)


class RenameMachine(BaseModel):
    name: str | None = Field(default=None, max_length=120)

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        if value and any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Machine name contains control characters")
        return value.strip() or None if value else None


def owned_repo_ids(user_id, ids):
    if not ids:
        return set()
    result = (
        get_supabase_thread_safe()
        .table("folders")
        .select("id")
        .eq("user_id", user_id)
        .eq("kind", "repo")
        .in_("id", list(ids))
        .execute()
        .data
    )
    return {row["id"] for row in result}


def inventory_values(user_id, data):
    report = MachineInventory.model_validate(data)
    repos = [row.model_dump(mode="json") for row in report.repositories]
    ids = {row["folder_id"] for row in repos}
    allowed = owned_repo_ids(user_id, ids)
    warnings = [row.model_dump(mode="json") for row in report.warnings]
    if ids - allowed:
        warnings.append({"code": "folder_unavailable", "observed_at": now_iso()})
    values = {
        "name": report.name,
        "os_name": report.os_name,
        "os_id": report.os_id,
        "architecture": report.architecture,
        "warnings": warnings,
    }
    if not any(row.code == "registry_unreadable" for row in report.warnings):
        values.update(
            inventory=[row for row in repos if row["folder_id"] in allowed],
            inventory_updated_at=now_iso(),
        )
    return values


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def token_hash(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def table():
    return get_supabase_thread_safe().table("remote_machines")


def public_machine(row):
    result = {k: row.get(k) for k in PUBLIC_COLUMNS.split(",")}
    result["name"] = row.get("custom_name") or row.get("name")
    last_seen = row.get("last_seen")
    recent = False
    if last_seen:
        # PostgreSQL trims fractional zeros; Python 3.10 fromisoformat rejects 1/2/4/5 digits.
        value = last_seen.replace("Z", "+00:00")
        try:
            seen = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")
        except ValueError:
            seen = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
        recent = (datetime.now(timezone.utc) - seen).total_seconds() < STALE_SECONDS
    result["online"] = bool(row.get("connected") and recent)
    return result


@router.post("/register")
async def register(body: Registration, user_id: str = Depends(get_current_user)):
    def write():
        return (
            table()
            .upsert(
                {
                    "id": str(body.id),
                    "user_id": user_id,
                    "token_hash": token_hash(body.secret),
                    "name": body.name,
                    "platform": body.platform,
                    "version": body.version,
                },
                on_conflict="user_id,id",
            )
            .execute()
        )

    await asyncio.to_thread(write)
    return {"id": str(body.id)}


@router.get("")
async def list_machines(user_id: str = Depends(get_current_user)):
    def read():
        return table().select(PUBLIC_COLUMNS).eq("user_id", user_id).order("name").execute().data

    return [public_machine(row) for row in await asyncio.to_thread(read)]


@router.patch("/{machine_id}")
async def rename_machine(
    machine_id: UUID, body: RenameMachine, user_id: str = Depends(get_current_user)
):
    def write():
        return (
            table()
            .update({"custom_name": body.name})
            .eq("id", str(machine_id))
            .eq("user_id", user_id)
            .execute()
            .data
        )

    rows = await asyncio.to_thread(write)
    if not rows:
        raise HTTPException(404, "Machine not found")
    return public_machine(rows[0])


async def receive_small_json(socket, timeout, max_bytes=1024):
    raw = await asyncio.wait_for(socket.receive_text(), timeout=timeout)
    if len(raw.encode("utf8")) > max_bytes:
        raise ValueError("Message too large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Expected object")
    return value


@router.websocket("/connect")
async def connect(socket: WebSocket):
    # Secrets travel in the first encrypted message, never in URLs/access logs.
    await socket.accept()
    row = None
    connection_id = str(uuid4())
    try:
        hello = await receive_small_json(socket, 10)
        machine_id = str(UUID(hello.get("id", "")))
        secret = hello.get("secret")
        if hello.get("type") != "hello" or not isinstance(secret, str) or len(secret) != 64:
            raise ValueError("Invalid hello")
        version = hello.get("version")
        if version is not None and (
            not isinstance(version, str)
            or len(version) > 40
            or not re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version)
        ):
            raise ValueError("Invalid Manabi version")

        def authenticate():
            return (
                table()
                .select("user_id,id")
                .eq("id", machine_id)
                .eq("token_hash", token_hash(secret))
                .execute()
                .data
            )

        rows = await asyncio.to_thread(authenticate)
        if len(rows) != 1:
            await socket.close(code=4401)
            return
        row = rows[0]

        def update(values, fenced=True):
            query = table().update(values).eq("id", row["id"]).eq("user_id", row["user_id"])
            if fenced:
                query = query.eq("connection_id", connection_id)
            return query.execute().data

        connection_values = {
            "connection_id": connection_id,
            "connected": True,
            "connected_at": now_iso(),
            "last_seen": now_iso(),
        }
        if version is not None:
            connection_values["version"] = version
        await asyncio.to_thread(update, connection_values, False)
        await socket.send_json({"type": "ready", "heartbeat_seconds": HEARTBEAT_SECONDS})
        while True:
            message = await receive_small_json(socket, HEARTBEAT_SECONDS * 2 + 10, 256_000)
            if message.get("type") == "inventory":
                revision = message.get("revision", "")
                if not isinstance(revision, str) or len(revision) != 64:
                    raise ValueError("Invalid inventory revision")
                try:
                    values = await asyncio.to_thread(
                        inventory_values, row["user_id"], message.get("data")
                    )
                    updated = await asyncio.to_thread(update, values)
                    if not updated:
                        await socket.close(code=4409)
                        return
                    await socket.send_json({"type": "inventory_ack", "revision": revision})
                except (ValidationError, ValueError, TypeError):
                    await asyncio.to_thread(
                        update,
                        {"warnings": [{"code": "inventory_rejected", "observed_at": now_iso()}]},
                    )
                    await socket.send_json({"type": "inventory_error"})
                continue
            if message.get("type") != "heartbeat":
                raise ValueError("Expected heartbeat")
            updated = await asyncio.to_thread(update, {"last_seen": now_iso()})
            if not updated:
                await socket.close(code=4409)
                return
            await socket.send_json({"type": "ack"})
    except (asyncio.TimeoutError, ValueError, TypeError, WebSocketDisconnect):
        try:
            await socket.close(code=4400)
        except RuntimeError:
            pass
    except Exception:
        log.exception("Manabi connection failed")
        try:
            await socket.close(code=1011)
        except RuntimeError:
            pass
    finally:
        if row:
            try:
                # ASGI servers cancel the connection scope during teardown.
                with anyio.move_on_after(5, shield=True):
                    await anyio.to_thread.run_sync(
                        lambda: update({"connected": False}), abandon_on_cancel=True
                    )
            except Exception:
                # Last-seen expiry still marks this machine offline after process/DB failures.
                log.warning("Could not clear Manabi presence", exc_info=True)
