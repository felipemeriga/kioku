"""Immutable execution authority established by trusted request handlers."""

import hashlib
import json
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from uuid import uuid4

import jwt


@dataclass(frozen=True)
class ExecutionScope:
    owner_id: str
    folder_ids: tuple[str, ...] = ()
    caller: str = "backend"
    conversation_id: str | None = None
    parent_job_id: str | None = None
    root_job_id: str | None = None
    ai_depth: int = 0
    harness_tool: bool = False
    tool_allowlist: tuple[str, ...] = ()
    expires_at: int | None = None
    admin: bool = False


_current: ContextVar[ExecutionScope | None] = ContextVar("execution_scope", default=None)


def current_scope() -> ExecutionScope | None:
    return _current.get()


def document_scope(owner_id: str, folder_id: str | None) -> ExecutionScope:
    """Narrow an existing caller grant, or bind a trusted ingestion job's owner."""
    folders = (folder_id,) if folder_id else ()
    existing = current_scope()
    if existing is None:
        return ExecutionScope(owner_id, folders)
    if existing.owner_id != owner_id or not set(folders).issubset(existing.folder_ids):
        raise PermissionError("document contextualization is outside caller scope")
    return replace(existing, folder_ids=folders)


@contextmanager
def execution_scope(scope: ExecutionScope):
    token = _current.set(scope)
    try:
        yield scope
    finally:
        _current.reset(token)


def operation_scope(operation: str) -> ExecutionScope | None:
    scope = current_scope()
    if scope is None:
        return None
    if scope.ai_depth > 0:
        raise PermissionError("nested generation cannot delegate")
    if scope.harness_tool:
        if operation != "text_to_sql" or not scope.parent_job_id:
            raise PermissionError("harness tool generation is forbidden")
        return replace(scope, ai_depth=1)
    return scope


def sign_capability(
    scope: ExecutionScope,
    operation: str,
    profile: str | None,
    *,
    ttl: int = 900,
    request: dict | None = None,
) -> str:
    if ttl < 1 or ttl > 1800:
        raise ValueError("capability lifetime outside allowed range")
    if scope.ai_depth and (
        scope.ai_depth != 1 or operation != "text_to_sql" or profile != "metadata_child"
    ):
        raise PermissionError("invalid metadata delegation")
    now = int(time.time())
    expiry = min(now + ttl, scope.expires_at) if scope.expires_at else now + ttl
    if expiry <= now:
        raise PermissionError("execution grant expired")
    claims = {
        "iss": "kioku-backend",
        "aud": "tsukai",
        "sub": scope.caller,
        "owner_id": scope.owner_id,
        "folder_ids": list(scope.folder_ids),
        "operations": [operation],
        "profiles": [profile] if profile else [],
        "tool_allowlist": list(scope.tool_allowlist),
        "iat": now,
        "exp": expiry,
        "jti": str(uuid4()),
        "ai_depth": scope.ai_depth,
    }
    if scope.admin:
        if (
            scope.caller != "backend"
            or operation != "runtime.sessions.read"
            or profile is not None
            or scope.folder_ids
            or scope.tool_allowlist
            or scope.ai_depth
            or scope.parent_job_id
        ):
            raise PermissionError("invalid administrative capability")
        claims["admin"] = True
    if request is not None:
        claims["request_sha256"] = hashlib.sha256(
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    if scope.parent_job_id:
        claims["parent_job_id"] = scope.parent_job_id
    if scope.root_job_id:
        claims["root_job_id"] = scope.root_job_id
    return jwt.encode(claims, os.environ["TSUKAI_CAPABILITY_KEY"], algorithm="HS256")
