#!/usr/bin/env python3
"""Native protocol fixture, never a production adapter or paid model."""

import json
import os
import sys
import time

if "--version" in sys.argv:
    print("2.1.285 (Claude Code)")
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
    emit(
        {
            "type": "result",
            "is_error": True,
            "subtype": "error",
            "result": "OAuth login expired private-diagnostic",
        }
    )
    raise SystemExit(1)
if "MISSING" in prompt:
    emit({"type": "system", "secret": "private-diagnostic"})
    raise SystemExit
emit({"type": "system", "subtype": "init", "private": "private-diagnostic"})
emit(
    {
        "type": "stream_event",
        "event": {"delta": {"type": "thinking_delta", "thinking": "private-diagnostic"}},
    }
)
emit({"type": "stream_event", "event": {"delta": {"type": "text_delta", "text": "Provisional "}}})
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
    result["structured_output"] = {"answer": "grounded"}
    if "INVALID" in prompt and "Previous attempt failed validation" not in prompt:
        result["structured_output"] = {"answer": 17}
emit(result)
