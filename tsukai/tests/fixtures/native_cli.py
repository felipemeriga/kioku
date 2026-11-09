#!/usr/bin/env python3
"""Native protocol fixture, never a production adapter or paid model."""

import json
import os
import subprocess
import sys
import time
import uuid

if "--version" in sys.argv:
    print("2.1.318 (Claude Code)")
    raise SystemExit
prompt = sys.stdin.read()
session = (
    sys.argv[sys.argv.index("--resume") + 1]
    if "--resume" in sys.argv
    else sys.argv[sys.argv.index("--session-id") + 1]
)


def emit(value):
    print(json.dumps(value), flush=True)


if "SLEEP" in prompt:
    time.sleep(30)
if "STDERR" in prompt:
    sys.stderr.write("private-diagnostic " * 100000)
    sys.stderr.flush()
if "PERMISSION" in prompt:
    emit({"type": "permission_request", "private": "secret"})
    time.sleep(30)
if "AUTH" in prompt:
    emit({"type": "system", "subtype": "init", "session_id": session})
    emit(
        {
            "type": "result",
            "session_id": session,
            "is_error": True,
            "subtype": "error",
            "result": "OAuth login expired private-diagnostic",
        }
    )
    raise SystemExit(1)
if prompt == "MISSING":
    emit({"type": "system", "secret": "private-diagnostic"})
    raise SystemExit
if "NO_INIT" not in prompt:
    emit(
        {
            "type": "system",
            "subtype": "init",
            "session_id": str(uuid.uuid4()) if "FOREIGN_INIT" in prompt else session,
            "private": "private-diagnostic",
            "mcp_servers": [
                {"name": "private-diagnostic-server", "status": "connected"},
                {"name": "private-diagnostic-failure", "status": "failed"},
            ],
        }
    )
emit(
    {
        "type": "stream_event",
        "event": {"delta": {"type": "thinking_delta", "thinking": "private-diagnostic"}},
    }
)
emit({"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "Provisional "}}})
if "ORPHAN" in prompt:
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);time.sleep(60)",
        ]
    )
    time.sleep(0.1)
    emit(
        {
            "type": "stream_event",
            "event": {"delta": {"type": "text_delta", "text": "child:" + str(child.pid)}},
        }
    )
    raise SystemExit
if "TEXT_EOF" in prompt:
    raise SystemExit
result = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "session_id": session,
    "result": "Canonical answer.",
    "total_cost_usd": 0.001,
    "modelUsage": {
        "fixture": {
            "inputTokens": 10,
            "outputTokens": 4,
            "cacheReadInputTokens": 0,
            "cacheCreationInputTokens": 0,
        }
    },
}
if "INSPECT" in prompt:
    result["result"] = json.dumps(
        {
            "args": sys.argv[1:],
            "environment_names": list(os.environ),
            "max_tokens": os.getenv("CLAUDE_CODE_MAX_OUTPUT_TOKENS"),
        }
    )
if "--json-schema" in sys.argv:
    schema = json.loads(sys.argv[sys.argv.index("--json-schema") + 1])
    if any(key in schema for key in ("oneOf", "anyOf", "allOf")):
        result.update(
            is_error=True,
            result="API Error 400: tools.input_schema cannot contain top level oneOf/anyOf/allOf",
            total_cost_usd=0,
        )
        emit(result)
        raise SystemExit(1)
    body = {"answer": "grounded"}
    if "ENVELOPE" in prompt:
        body = {
            "schema_version": 1,
            "outcome": "completed",
            "data": {"answer": "grounded"},
            "missing_inputs": [],
            "failure": None,
            "warnings": [],
        }
    if "INVALID" in prompt and "Previous attempt failed validation" not in prompt:
        body = {"answer": 17}
    if "BAD_UNION" in prompt:
        body.update(
            outcome="needs_input", missing_inputs=[{"field": "evidence", "reason": "missing"}]
        )
    wrapped = schema.get("type") == "object" and set(schema.get("properties", {})) == {"result"}
    result["structured_output"] = {"result": body} if wrapped else body
    if "BAD_WRAPPER" in prompt:
        result["structured_output"] = {"result": body, "extra": "not part of transport"}
if "MISSING_FINAL_ID" in prompt:
    result.pop("session_id")
if "FOREIGN_FINAL" in prompt:
    result["session_id"] = str(uuid.uuid4())
if "AGGREGATE" in prompt:
    result["modelUsage"]["fixture"]["outputTokens"] = 2000
emit(result)
if "NONZERO" in prompt:
    raise SystemExit(1)
