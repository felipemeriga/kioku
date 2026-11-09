"""Isolate CLI/model latency using the installed adapter, without DB admission.

Run in a pinned Tsukai environment. No hooks, shell/file tools or domain writes.
An optional existing MCP config isolates connection overhead; the prompt requests
no tool use. These diagnostic timings are not end-to-end chat acceptance.
"""

import argparse
import asyncio
import json
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from tsukai.config import Settings
from tsukai.native import NativeRunner
from tsukai.validation import NativeError

from tsukai.protocol import JobRequest


async def run(models, mcp=None):
    native = NativeRunner(Settings())
    await native.verify_version()
    for model in models:
        with tempfile.TemporaryDirectory(prefix="kioku-latency-") as workspace:
            session = str(uuid4())
            conversation = str(uuid4())
            for resume in (False, True):
                attempt = {
                    "id": str(uuid4()),
                    "native_session_id": session,
                    "resume": resume,
                    "counter_segment": 0,
                }
                req = JobRequest(
                    idempotency_key=attempt["id"],
                    owner_id="isolated-latency-benchmark",
                    caller="backend",
                    operation="rag_agent",
                    profile="chat",
                    conversation_id=conversation,
                    model=model,
                    reasoning_effort="low",
                    max_tokens=6000,
                    max_turns=2,
                    prompt="Reply with exactly LATENCY_OK. Do not use tools.",
                    system_prompt="This is a latency control. Follow the user's output instruction.",
                    tool_allowlist=[
                        "knowledge_base_search",
                        "search_agent_history",
                        "read_agent_evidence",
                    ]
                    if mcp
                    else [],
                    tool_capability_ref=attempt["id"] if mcp else None,
                )

                async def emit(*_):
                    pass

                started = time.monotonic()
                try:
                    result = await native.run(
                        {"attempt": attempt, "workspace": workspace}, req, emit, mcp=mcp
                    )
                    print(
                        json.dumps(
                            {
                                "model": model,
                                "resume": resume,
                                "mcp_attached": bool(mcp),
                                "seconds": time.monotonic() - started,
                                "answer_valid": result["text"].strip() == "LATENCY_OK",
                                "first_event_at": attempt.get("first_event_at"),
                                "first_text_at": attempt.get("first_text_at"),
                                "usage": result.get("usage"),
                            }
                        ),
                        flush=True,
                    )
                except (TimeoutError, NativeError, OSError) as exc:
                    print(
                        json.dumps(
                            {
                                "model": model,
                                "resume": resume,
                                "seconds": time.monotonic() - started,
                                "error_code": getattr(exc, "code", type(exc).__name__),
                            }
                        ),
                        flush=True,
                    )
                    break  # Cannot resume a session whose completion is uncertain.


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--mcp-config", type=Path)
    args = parser.parse_args()
    config = json.loads(args.mcp_config.read_text()) if args.mcp_config else None
    asyncio.run(run(args.models, config))
