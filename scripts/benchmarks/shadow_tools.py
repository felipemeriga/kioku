"""Temporary authenticated, read-only tools for an isolated retrieval evaluation.

Run beside the backend with a private config containing owner_id, folder_ids,
token (at least32 characters). Never mount this in the production application.
The source/DB routines are the candidate implementation; citation allocation
is in memory so evaluation does not mutate chats, documents or originals.
"""

import argparse
import asyncio
import hmac
import inspect
import json
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from threading import RLock
from typing import Annotated

import uvicorn
from db.client import get_supabase_thread_safe
from fastapi import FastAPI, HTTPException
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from services.ai import native_tools
from services.citations import CitationRegistry
from services.evidence_prefetch import prefetch
from services.tools import execute_tool
from starlette.responses import JSONResponse


def application(config):
    if len(config["token"]) < 32 or not config["owner_id"] or not config["folder_ids"]:
        raise ValueError("A private owner-scoped evaluation config is required")
    cases, active = {}, ContextVar("evaluation_case", default=None)
    server = FastMCP(
        "Kioku",
        stateless_http=True,
        streamable_http_path="/",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[
                "localhost",
                "127.0.0.1",
                "localhost:*",
                "127.0.0.1:*",
                f"kioku-backend:{config.get('port', 9512)}",
            ],
            allowed_origins=[],
        ),
    )

    class Registry(CitationRegistry):
        def __init__(self):
            super().__init__()
            self.lock = RLock()

        def register(self, result):
            with self.lock:
                return super().register(result)

    def run(name, arguments, case=None):
        state = cases[case or active.get()]
        trace = {"name": name, "input": arguments, "sources": []}
        result = execute_tool(
            name,
            arguments,
            config["owner_id"],
            fast_mode=True,
            scope_folder_ids=state["folders"],
            citations=state["citations"],
            debug_retrieval=trace["sources"],
            full_debug=True,
        )
        trace["result"] = result
        state["calls"].append(trace)
        return result

    @server.tool(description=inspect.getdoc(native_tools.knowledge_base_search))
    def knowledge_base_search(
        query: str, created_after: str | None = None, created_before: str | None = None
    ) -> str:
        """Search scoped documents and indexed code with real hybrid retrieval."""
        return run(
            "knowledge_base_search",
            {k: v for k, v in locals().items() if not callable(v)},
        )

    @server.tool(description=inspect.getdoc(native_tools.code_graph_lookup))
    def code_graph_lookup(operation: str, symbol: str = "", path: str = "") -> str:
        """Read indexed code definitions, references, impact or outline."""
        return run(
            "code_graph_lookup", {k: v for k, v in locals().items() if not callable(v)}
        )

    @server.tool(description=inspect.getdoc(native_tools.search_agent_history))
    def search_agent_history(
        query: str = "",
        folder: str | None = None,
        from_date: str | None = None,
        through_date: str | None = None,
        as_of: str | None = None,
        timezone: str = "UTC",
        session: str | None = None,
        order: str = "chronological",
        limit: Annotated[int, Field(ge=1, le=10)] = 10,
        offset: int = 0,
        queries: list[str] | None = None,
    ) -> str:
        """Search dated original evidence; keep scope, cutoff and coverage."""
        return run(
            "search_agent_history",
            {k: v for k, v in locals().items() if v is not None and not callable(v)},
        )

    @server.tool(description=inspect.getdoc(native_tools.read_agent_evidence))
    def read_agent_evidence(
        reference: str,
        before_records: Annotated[int, Field(ge=0, le=1)] = 1,
        after_records: Annotated[int, Field(ge=0, le=1)] = 1,
        char_limit: Annotated[int, Field(ge=1000, le=8000)] = 4000,
    ) -> str:
        """Read bounded originals or journal reports; follow next_reference for more journal text."""
        return run(
            "read_agent_evidence",
            {k: v for k, v in locals().items() if not callable(v)},
        )

    @server.tool()
    def recent_changes() -> str:
        """Read the scoped Git-derived change digest, not agent-work history."""
        return run("recent_changes", {})

    @asynccontextmanager
    async def lifespan(_):
        async with server.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)

    class Prepare(BaseModel):
        case: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
        question: str = Field(min_length=1, max_length=4000)
        folder_ids: list[str] = Field(min_length=1, max_length=100)
        timezone: str = "America/Sao_Paulo"
        skip_prefetch: bool = False

    @app.post("/prepare")
    async def prepare(body: Prepare):
        if not set(body.folder_ids) <= set(config["folder_ids"]):
            raise HTTPException(403, "Evaluation scope cannot expand")
        if body.case in cases:
            raise HTTPException(409, "Evaluation case already prepared")
        owned = (
            get_supabase_thread_safe()
            .table("folders")
            .select("id,name")
            .eq("user_id", config["owner_id"])
            .in_("id", body.folder_ids)
            .execute()
            .data
        )
        if {r["id"] for r in owned} != set(body.folder_ids):
            raise HTTPException(403, "Evaluation scope changed")
        state = {"folders": body.folder_ids, "citations": Registry(), "calls": []}
        cases[body.case] = state
        if body.skip_prefetch:
            evidence = json.dumps(
                {
                    "status": "not_prefetched",
                    "scope": owned,
                    "instruction": "Retrieve supporting evidence with the available tools.",
                }
            )
        else:
            evidence, _ = await asyncio.to_thread(
                prefetch,
                body.question,
                body.timezone,
                lambda name, args: run(name, args, body.case),
                folders=owned,
            )
        state["evidence"] = evidence
        return {"evidence": evidence, "citations": state["citations"].entries()}

    @app.get("/result/{case}")
    async def result(case: str):
        if case not in cases:
            raise HTTPException(404, "Unknown evaluation case")
        state = cases[case]
        return {
            "evidence": state["evidence"],
            "citations": state["citations"].entries(),
            "calls": state["calls"],
        }

    app.mount("/mcp", server.streamable_http_app())

    class Auth:
        async def __call__(self, scope, receive, send):
            if scope["type"] != "http":
                return await app(scope, receive, send)
            headers = dict(scope.get("headers", []))
            if not hmac.compare_digest(
                headers.get(b"authorization", b""),
                ("Bearer " + config["token"]).encode(),
            ):
                return await JSONResponse({"error": "Unauthorized"}, 401)(
                    scope, receive, send
                )
            case = headers.get(b"x-kioku-benchmark-case", b"").decode()
            if scope["path"].startswith("/mcp") and case not in cases:
                return await JSONResponse({"error": "Unknown case"}, 404)(
                    scope, receive, send
                )
            token = active.set(case)
            try:
                await app(scope, receive, send)
            finally:
                active.reset(token)

    return Auth()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9512)
    args = parser.parse_args()
    uvicorn.run(
        application(json.loads(args.config.read_text())), host=args.host, port=args.port
    )
