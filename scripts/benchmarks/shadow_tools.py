"""Temporary authenticated, read-only tools for an isolated retrieval evaluation.

Run beside the backend with a private config containing owner_id, folder_ids,
token (at least32 characters). Never mount this in the production application.
The source/DB routines are the candidate implementation; citation allocation
is in memory so evaluation does not mutate chats, documents or originals.
"""

import argparse
import asyncio
import hashlib
import hmac
import inspect
import json
import sys
from contextlib import asynccontextmanager
from contextvars import ContextVar
from pathlib import Path
from threading import RLock

import uvicorn
from db.client import get_supabase_thread_safe
from fastapi import FastAPI, HTTPException
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from services import rag
from services.agent_memory_tools import memory_time_context
from services.ai import native_tools
from services.ai.chat import (
    NATIVE_CHAT_MAX_TOKENS,
    NATIVE_CHAT_MAX_TURNS,
    NATIVE_CHAT_PROMPT,
    native_chat_prompt,
)
from services.citations import CitationRegistry
from services.evidence_prefetch import ANSWER_INSTRUCTION, prefetch
from services.tools import execute_tool
from starlette.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_guard import verify_sources


def application(config):
    if len(config["token"]) < 32 or not config["owner_id"] or not config["folder_ids"]:
        raise ValueError("A private owner-scoped evaluation config is required")
    source_files = [
        Path(inspect.getfile(inspect.unwrap(fn))).resolve()
        for fn in [
            prefetch,
            execute_tool,
            native_chat_prompt,
            memory_time_context,
            native_tools.create_native_mcp,
        ]
    ]
    if config.get("remote") and any(
        not path.is_relative_to(Path(config["remote"]) / "backend")
        for path in source_files
    ):
        raise ValueError("Retrieval did not load from the expected candidate source")
    source_files.append(Path(inspect.getfile(rag)).resolve())
    source_lock = verify_sources(config, source_files)
    if (
        source_lock
        and hashlib.sha256(NATIVE_CHAT_PROMPT.encode()).hexdigest()
        != source_lock["system_prompt_sha256"]
    ):
        raise ValueError("Loaded production system prompt differs from its source lock")
    source_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in source_files
    }
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
        # External search and durable child jobs cannot be evaluated by this
        # read-only adapter. Never substitute the legacy metadata API path.
        if name in {"query_documents_metadata", "web_search"}:
            state.setdefault("unsupported_calls", []).append(name)
            return "This evaluation cannot execute this tool; record this case as unsuccessful."
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

    native_tools.create_native_mcp(server=server, runner=run)

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
        time_context = memory_time_context(body.timezone)
        prefetch_calls = None
        if body.skip_prefetch:
            evidence = json.dumps(
                {
                    "status": "not_prefetched",
                    "scope": owned,
                    "instruction": "Retrieve supporting evidence with the available tools.",
                }
            )
        else:
            evidence, prefetch_calls = await asyncio.to_thread(
                prefetch,
                body.question,
                body.timezone,
                lambda name, args: run(name, args, body.case),
                folders=owned,
            )
        state["evidence"] = evidence
        return {
            "evidence": evidence,
            "citations": state["citations"].entries(),
            "answer_instruction": ANSWER_INSTRUCTION,
            "source_lock": source_lock,
            "chat_contract": {
                "system_prompt": NATIVE_CHAT_PROMPT,
                "prompt": native_chat_prompt(
                    content=body.question,
                    history=[],
                    turn_id=body.case,
                    time_context=time_context,
                    evidence=evidence,
                ),
                "max_tokens": NATIVE_CHAT_MAX_TOKENS,
                "max_turns": NATIVE_CHAT_MAX_TURNS,
                "tool_allowlist": [t.name for t in await server.list_tools()]
                if prefetch_calls is None or prefetch_calls
                else [],
            },
        }

    @app.get("/result/{case}")
    async def result(case: str):
        if case not in cases:
            raise HTTPException(404, "Unknown evaluation case")
        state = cases[case]
        return {
            "evidence": state["evidence"],
            "citations": state["citations"].entries(),
            "calls": state["calls"],
            "unsupported_calls": state.get("unsupported_calls", []),
            "source_sha256": source_hashes,
            "source_lock": source_lock,
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
