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
from redis.exceptions import WatchError

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
    await _get_redis().set(_REQ_PREFIX + rec["request_id"], json.dumps(rec), ex=_remaining_ttl(rec))


async def _transition(request_id: str, accept, update) -> bool:
    """Compare-and-set the TTL-bound request so competing browser actions cannot win twice."""
    r = _get_redis()
    key = _REQ_PREFIX + request_id
    async with r.pipeline(transaction=True) as pipe:
        try:
            await pipe.watch(key)
            raw = await pipe.get(key)
            rec = json.loads(raw) if raw else None
            if not rec or rec["expires_at"] <= time.time() or not accept(rec):
                return False
            update(rec)
            pipe.multi()
            pipe.set(key, json.dumps(rec), ex=_remaining_ttl(rec))
            await pipe.execute()
            return True
        except WatchError:
            return False


async def claim_authorization(request_id: str, user_id: str) -> str | None:
    nonce = secrets.token_urlsafe(24)
    ok = await _transition(
        request_id,
        lambda rec: rec["status"] == "pending",
        lambda rec: rec.update(status="authorizing", authorization_nonce=nonce, user_id=user_id),
    )
    return nonce if ok else None


async def finish_authorization(request_id: str, nonce: str, tokens: dict | None) -> bool:
    def update(rec):
        rec.pop("authorization_nonce", None)
        rec.update(status="authorized" if tokens else "pending", tokens=tokens)

    return await _transition(
        request_id,
        lambda rec: rec["status"] == "authorizing" and rec.get("authorization_nonce") == nonce,
        update,
    )


async def authorize(request_id: str, tokens: dict) -> bool:
    return await _transition(
        request_id,
        lambda rec: rec["status"] == "pending",
        lambda rec: rec.update(status="authorized", tokens=tokens),
    )


async def deny(request_id: str) -> bool:
    return await _transition(
        request_id,
        lambda rec: rec["status"] in ("pending", "authorizing"),
        lambda rec: rec.update(status="denied", tokens=None),
    )


async def _delete(rec: dict) -> None:
    r = _get_redis()
    await r.delete(_REQ_PREFIX + rec["request_id"])
    await r.delete(_DEV_PREFIX + rec["device_hash"])


async def consume_by_device_code(device_code: str) -> dict:
    r = _get_redis()
    device_key = _DEV_PREFIX + hash_device_code(device_code)
    request_id = await r.get(device_key)
    if not request_id:
        return {"status": "expired", "tokens": None}
    request_key = _REQ_PREFIX + request_id
    async with r.pipeline(transaction=True) as pipe:
        try:
            await pipe.watch(device_key, request_key)
            if await pipe.get(device_key) != request_id:
                return {"status": "expired", "tokens": None}
            raw = await pipe.get(request_key)
            rec = json.loads(raw) if raw else None
            if not rec or rec["expires_at"] <= time.time():
                return {"status": "expired", "tokens": None}
            if rec["status"] == "authorized":
                tokens = rec["tokens"]
                pipe.multi()
                pipe.delete(request_key, device_key)
                await pipe.execute()
                return {"status": "authorized", "tokens": tokens}
            return {
                "status": "pending" if rec["status"] == "authorizing" else rec["status"],
                "tokens": None,
            }
        except WatchError:
            # A competing poll/approval won; retry polling without disclosing tokens twice.
            return {"status": "pending", "tokens": None}
