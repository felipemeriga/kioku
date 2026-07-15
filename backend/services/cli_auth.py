"""Redis-backed pending-request store for CLI browser-handoff login.

Two secrets per request: a public `request_id` (goes in the browser URL)
and a secret `device_code` (stays in the CLI, used to poll). Only
sha256(device_code) is persisted. Records are single-use and TTL-bound.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time

from redis.asyncio import from_url

TTL_SECONDS = 300
_REQ_PREFIX = "cli_auth:req:"
_DEV_PREFIX = "cli_auth:dev:"  # sha256(device_code) -> request_id pointer


def _get_redis():
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    return from_url(url, decode_responses=True)


def hash_device_code(device_code: str) -> str:
    return hashlib.sha256(device_code.encode()).hexdigest()


def _remaining_ttl(rec: dict) -> int:
    return max(1, int(rec["expires_at"] - time.time()))


async def create_request(hostname: str, os_name: str) -> dict:
    request_id = secrets.token_urlsafe(16)
    device_code = secrets.token_urlsafe(32)
    device_hash = hash_device_code(device_code)
    rec = {
        "request_id": request_id,
        "device_hash": device_hash,
        "hostname": hostname[:120],
        "os": os_name[:60],
        "status": "pending",
        "expires_at": time.time() + TTL_SECONDS,
        "tokens": None,
    }
    r = _get_redis()
    await r.set(_REQ_PREFIX + request_id, json.dumps(rec), ex=TTL_SECONDS)
    await r.set(_DEV_PREFIX + device_hash, request_id, ex=TTL_SECONDS)
    return {"request_id": request_id, "device_code": device_code, "expires_in": TTL_SECONDS}


async def get_by_request_id(request_id: str) -> dict | None:
    raw = await _get_redis().get(_REQ_PREFIX + request_id)
    return json.loads(raw) if raw else None


async def _save(rec: dict) -> None:
    await _get_redis().set(
        _REQ_PREFIX + rec["request_id"], json.dumps(rec), ex=_remaining_ttl(rec)
    )


async def authorize(request_id: str, tokens: dict) -> bool:
    rec = await get_by_request_id(request_id)
    if not rec or rec["status"] != "pending":
        return False
    rec["status"] = "authorized"
    rec["tokens"] = tokens
    await _save(rec)
    return True


async def deny(request_id: str) -> bool:
    rec = await get_by_request_id(request_id)
    if not rec or rec["status"] != "pending":
        return False
    rec["status"] = "denied"
    await _save(rec)
    return True


async def _delete(rec: dict) -> None:
    r = _get_redis()
    await r.delete(_REQ_PREFIX + rec["request_id"])
    await r.delete(_DEV_PREFIX + rec["device_hash"])


async def consume_by_device_code(device_code: str) -> dict:
    r = _get_redis()
    request_id = await r.get(_DEV_PREFIX + hash_device_code(device_code))
    if not request_id:
        return {"status": "expired", "tokens": None}
    rec = await get_by_request_id(request_id)
    if not rec:
        return {"status": "expired", "tokens": None}
    if rec["status"] == "authorized":
        tokens = rec["tokens"]
        await _delete(rec)  # single-use
        return {"status": "authorized", "tokens": tokens}
    return {"status": rec["status"], "tokens": None}
