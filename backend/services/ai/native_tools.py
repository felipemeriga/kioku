"""Read-only Kioku MCP surface for active, scope-bound native attempts."""

import asyncio
import hashlib
import hmac
import json
import os
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import uuid4

import jwt
from fastapi import APIRouter, HTTPException, Request
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel
from starlette.responses import JSONResponse

from db.client import get_supabase_thread_safe
from services.ai.chat import owned_turn, turn_scope
from services.ai.evidence import (
    DurableCitations,
    materialize_bootstrap,
    save_trace,
    scope_locations,
)
from services.ai.facade import client_for
from services.ai.scope import ExecutionScope, execution_scope
from services.tools import execute_tool

router = APIRouter()
_authority: ContextVar[dict | None] = ContextVar("native_tool_authority", default=None)


class ToolCapabilityRequest(BaseModel):
    job_id: str
    attempt_id: str
    owner_id: str
    folder_ids: list[str]
    tool_allowlist: list[str]
    tool_capability_ref: str
    deadline: str | float


def verify_attempt(turn: dict, attempt_id: str) -> dict:
    scope = turn_scope(turn)
    request = turn["request"]
    client = client_for(scope, request["operation"], request["profile"])
    try:
        attempt = client.active_attempt(turn["job_id"], attempt_id)
    finally:
        client.close()
    if not attempt.get("active") or attempt.get("owner_id") != turn["owner_id"]:
        raise HTTPException(403, "Inactive native tool attempt")
    if set(attempt["folder_ids"]) != set(scope.folder_ids) or attempt.get("ai_depth", 0) != 0:
        raise HTTPException(403, "Native attempt scope mismatch")
    return attempt


@router.post("/internal/tsukai/tool-capability")
def mint_tool_capability(body: ToolCapabilityRequest, request: Request):
    supplied = request.headers.get("Authorization", "")
    expected = "Bearer " + os.environ.get("TSUKAI_SERVICE_TOKEN", "")
    if not os.environ.get("TSUKAI_SERVICE_TOKEN") or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Invalid execution service identity")
    turn = owned_turn(body.owner_id, turn_id=body.tool_capability_ref)
    if turn.get("job_id") not in (None, body.job_id):
        raise HTTPException(403, "Execution mapping mismatch")
    if not turn.get("job_id"):
        candidate = {**turn, "job_id": body.job_id}
        scope = turn_scope(candidate)
        client = client_for(scope, candidate["request"]["operation"], "chat")
        try:
            accepted = client.status(body.job_id)
        finally:
            client.close()
        expected_digest = hashlib.sha256(
            json.dumps(turn["request"], sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if accepted.get("request_sha256") != expected_digest:
            raise HTTPException(403, "Accepted request does not match prepared turn")
        get_supabase_thread_safe().table("tsukai_chat_turns").update(
            {
                "job_id": body.job_id,
                "state": "submitted",
            }
        ).eq("id", turn["id"]).eq("owner_id", body.owner_id).is_("job_id", "null").execute()
        turn = candidate
    prepared = turn["request"]
    if (
        body.tool_capability_ref != turn["id"]
        or prepared["profile"] != "chat"
        or set(body.folder_ids) != set(prepared["folder_ids"])
        or set(body.tool_allowlist) != set(prepared["tool_allowlist"])
    ):
        raise HTTPException(403, "Tool grant does not match accepted execution")
    attempt = verify_attempt(turn, body.attempt_id)
    deadline = attempt["deadline"]
    if isinstance(deadline, str):
        deadline = datetime.fromisoformat(deadline.replace("Z", "+00:00")).timestamp()
    now = int(time.time())
    expires = min(int(deadline) + 30, now + 360)
    if expires <= now:
        raise HTTPException(403, "Attempt deadline expired")
    materialize_bootstrap(turn, body.attempt_id)
    grant = jwt.encode(
        {
            "iss": "kioku-backend",
            "aud": "kioku-native-tools",
            "iat": now,
            "exp": expires,
            "jti": str(uuid4()),
            "owner_id": body.owner_id,
            "job_id": body.job_id,
            "attempt_id": body.attempt_id,
            "folder_ids": body.folder_ids,
            "tool_allowlist": body.tool_allowlist,
        },
        os.environ["TSUKAI_CAPABILITY_KEY"],
        algorithm="HS256",
    )
    # Deployment config is a server registry, never an incoming URL.
    return {"mcp_url": os.environ["TSUKAI_NATIVE_MCP_URL"], "capability": grant}


def authenticate_tool(token: str) -> dict:
    try:
        grant = jwt.decode(
            token,
            os.environ["TSUKAI_CAPABILITY_KEY"],
            algorithms=["HS256"],
            audience="kioku-native-tools",
            issuer="kioku-backend",
            options={
                "require": ["exp", "iat", "jti", "job_id", "attempt_id", "owner_id"],
            },
        )
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid native tool capability") from None
    turn = owned_turn(grant["owner_id"], job_id=grant["job_id"])
    attempt = verify_attempt(turn, grant["attempt_id"])
    if set(grant["folder_ids"]) != set(attempt["folder_ids"]) or not set(
        grant["tool_allowlist"]
    ).issubset(attempt["tool_allowlist"]):
        raise HTTPException(403, "Tool scope changed")
    grant["scope_filename"] = turn["request"]["metadata"]["intent"].get("scope_filename")
    grant["turn_id"] = turn["id"]
    grant["conversation_id"] = turn["conversation_id"]
    grant["operation"] = turn["request"]["operation"]
    return grant


class NativeToolAuth:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        auth = dict(scope.get("headers", [])).get(b"authorization", b"").decode()
        try:
            if not auth.startswith("Bearer "):
                raise HTTPException(401, "Missing native tool capability")
            grant = await asyncio.to_thread(authenticate_tool, auth[7:])
        except HTTPException as exc:
            await JSONResponse({"error": exc.detail}, status_code=exc.status_code)(
                scope, receive, send
            )
            return
        token = _authority.set(grant)
        try:
            with execution_scope(
                ExecutionScope(
                    grant["owner_id"],
                    tuple(grant["folder_ids"]),
                    caller="backend",
                    parent_job_id=grant["job_id"],
                    root_job_id=grant["job_id"],
                    harness_tool=True,
                )
            ):
                await self.app(scope, receive, send)
        finally:
            _authority.reset(token)


def run_tool(name: str, arguments: dict) -> str:
    grant = _authority.get()
    if not grant or name not in grant["tool_allowlist"]:
        raise PermissionError("Tool unavailable for this execution")
    if not grant["folder_ids"] and name != "web_search":
        return "No accessible Kioku folders are in this turn's scope."
    scope = ExecutionScope(
        grant["owner_id"], tuple(grant["folder_ids"]), tool_allowlist=tuple(grant["tool_allowlist"])
    )
    client = client_for(scope, grant["operation"], "chat")
    invocation = str(uuid4())
    trace = {
        "trace_version": 1,
        "root_turn_id": grant["turn_id"],
        "conversation_id": grant.get("conversation_id"),
        "trace_id": invocation,
        "job_id": grant["job_id"],
        "attempt_id": grant["attempt_id"],
        "tool_call_id": invocation,
        "native_tool_use_id": None,
        "native_tool_use_id_availability": "Not exposed by the native CLI MCP transport",
        "name": name,
        "input": arguments,
        "query": arguments.get("query") or arguments.get("question"),
        "effective_scope": {
            **scope_locations(grant["owner_id"], grant["folder_ids"]),
            "filename": grant.get("scope_filename"),
        },
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
    }
    retrieval = []
    result = ""
    metadata_consumption = None

    def metadata_ready(consumed):
        nonlocal metadata_consumption
        metadata_consumption = consumed

    try:
        client.tool_event(grant["job_id"], grant["attempt_id"], "tool.started", trace)
        if name == "query_documents_metadata":
            from services.ai.metadata import metadata_query

            result = metadata_query(
                arguments["question"],
                {**grant, "tool_call_id": invocation},
                on_consumption=metadata_ready,
            )
        else:
            result = execute_tool(
                name,
                arguments,
                grant["owner_id"],
                fast_mode=True,
                scope_folder_ids=grant["folder_ids"],
                scope_filename=grant.get("scope_filename"),
                debug_retrieval=retrieval,
                citations=DurableCitations(
                    grant["job_id"],
                    grant["attempt_id"],
                    grant["owner_id"],
                    grant.get("conversation_id"),
                ),
                full_debug=True,
            )
        trace["status"] = "completed"
    except Exception as exc:
        trace["status"] = "failed"
        trace["error"] = {"code": type(exc).__name__, "message": "Kioku tool execution failed"}
        result = "Kioku tool execution failed; retry or report the missing evidence."
    finally:
        trace.update(
            {
                "sources": retrieval,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "result_sha256": hashlib.sha256(result.encode()).hexdigest(),
                "result_bytes": len(result.encode()),
                "result_preview": result[:1500],
            }
        )
        artifact = save_trace(
            grant["owner_id"],
            grant["job_id"],
            grant["attempt_id"],
            grant["folder_ids"],
            trace,
            result,
        )
        trace["result_ref"] = artifact
        if metadata_consumption:
            from services.ai.metadata import consume_metadata

            consume_metadata(metadata_consumption, artifact)
        # Live frames remain bounded; the authenticated artifact retains exact full result.
        preview = {
            **trace,
            "sources": [
                {**source, "content": source.get("content", "")[:1200]} for source in retrieval
            ],
            "result_preview": result[:1500],
        }
        try:
            if retrieval:
                client.tool_event(
                    grant["job_id"], grant["attempt_id"], "retrieval.completed", preview
                )
            client.tool_event(grant["job_id"], grant["attempt_id"], "tool.completed", preview)
        finally:
            client.close()
    return result


async def knowledge_base_search(
    query: str, created_after: str | None = None, created_before: str | None = None
) -> str:
    """Search real Kioku document and code evidence inside the authorized scope."""
    return await asyncio.to_thread(
        run_tool,
        "knowledge_base_search",
        {
            "query": query,
            "created_after": created_after,
            "created_before": created_before,
        },
    )


async def code_graph_lookup(operation: str, symbol: str = "", path: str = "") -> str:
    """Look up indexed definitions, references, impact or outline in this scope."""
    return await asyncio.to_thread(
        run_tool,
        "code_graph_lookup",
        {
            "operation": operation,
            "symbol": symbol,
            "path": path,
        },
    )


async def query_documents_metadata(question: str) -> str:
    """Query scoped document metadata through a bounded fresh child completion."""
    return await asyncio.to_thread(run_tool, "query_documents_metadata", {"question": question})


async def recent_changes() -> str:
    """Read the authoritative scoped repository activity summaries."""
    return await asyncio.to_thread(run_tool, "recent_changes", {})


async def web_search(query: str) -> str:
    """Search the web through Kioku's configured search provider."""
    return await asyncio.to_thread(run_tool, "web_search", {"query": query})


def create_native_mcp() -> FastMCP:
    server = FastMCP("Kioku", host="0.0.0.0", stateless_http=True, streamable_http_path="/")
    for tool in (
        knowledge_base_search,
        code_graph_lookup,
        query_documents_metadata,
        recent_changes,
        web_search,
    ):
        server.add_tool(tool)
    return server


native_mcp = create_native_mcp()
