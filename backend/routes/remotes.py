"""Manabi machine registration and outbound connection presence (no memory capture)."""

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from uuid import UUID, uuid4

import anyio
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from auth import get_current_user
from db.client import get_supabase_thread_safe

router = APIRouter(prefix="/api/remotes", tags=["remotes"])
log = logging.getLogger(__name__)
HEARTBEAT_SECONDS = 30
STALE_SECONDS = 90
PUBLIC_COLUMNS = "id,name,platform,version,created_at,connected_at,last_seen,connected"


class Registration(BaseModel):
    id: UUID
    secret: str = Field(pattern=r"^[a-f0-9]{64}$")
    name: str = Field(min_length=1, max_length=120)
    platform: str = Field(min_length=1, max_length=60)
    version: str = Field(min_length=1, max_length=40)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def token_hash(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def table():
    return get_supabase_thread_safe().table("remote_machines")


def public_machine(row):
    result = {k: row.get(k) for k in PUBLIC_COLUMNS.split(",")}
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


async def receive_small_json(socket, timeout):
    raw = await asyncio.wait_for(socket.receive_text(), timeout=timeout)
    if len(raw) > 1024:
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

        await asyncio.to_thread(
            update,
            {
                "connection_id": connection_id,
                "connected": True,
                "connected_at": now_iso(),
                "last_seen": now_iso(),
            },
            False,
        )
        await socket.send_json({"type": "ready", "heartbeat_seconds": HEARTBEAT_SECONDS})
        while True:
            message = await receive_small_json(socket, HEARTBEAT_SECONDS * 2 + 10)
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
