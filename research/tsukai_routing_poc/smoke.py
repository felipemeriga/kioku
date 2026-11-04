"""Functional routing smoke, including actual Mihari fixture adapter."""

import argparse
import http.client
import json
import sys
from pathlib import Path

import poc


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--runtime", type=Path, required=True)
    p.add_argument("--actual-mihari", action="store_true")
    p.add_argument(
        "--prior-poc-root",
        type=Path,
        default=Path("/tmp/kioku-claude-poc-server/project"),
    )
    a = p.parse_args()
    poc.KEY = (a.runtime / "fixture-key").read_bytes()
    checks = {}

    def call(engine, prompt, **extra):
        body = {
            "engine": engine,
            "path": "chat",
            "prompt": prompt,
            "capability": poc.capability("backend"),
            **extra,
        }
        return list(poc.request_stream(18781, body))

    for engine in ["api", "native"]:
        events = call(
            engine,
            "Use knowledge_base_search exactly once, then explain MAX_ATTEMPTS and event_id with a source citation. Do not claim deployment.",
            agent=True,
        )
        result = events[-1]
        checks[engine + "_harness_tools"] = {
            "passed": result.get("success")
            and any(e["type"] == "tool" for e in events)
            and "7" in result.get("text", ""),
            "events": events,
        }
    first = call(
        "native",
        "We chose PostgreSQL outbox and event_id as the idempotency key. Acknowledge.",
        stateful=True,
    )[-1]
    second = call(
        "native",
        "Which database pattern and idempotency key did we choose?",
        resume=first["session_id"],
    )[-1]
    checks["resumed_chat"] = {
        "passed": "PostgreSQL" in second["text"] and "event_id" in second["text"],
        "session_id": second["session_id"],
    }
    conn = http.client.HTTPConnection("127.0.0.1", 18781)
    bad = {
        "engine": "mock",
        "path": "mihari",
        "prompt": "x",
        "capability": poc.capability("mihari", user="other-owner"),
    }
    conn.request(
        "POST",
        "/invoke",
        json.dumps(bad),
        {"Authorization": "Bearer mihari", "Content-Type": "application/json"},
    )
    checks["scope_rejection"] = {"passed": conn.getresponse().status == 403}
    conn.close()
    (a.runtime / "smoke.json").write_text(json.dumps(checks, indent=2))
    print(json.dumps({k: v["passed"] for k, v in checks.items()}), flush=True)
    if a.actual_mihari:
        sys.path.insert(0, str(a.prior_poc_root / "research/claude_code_poc"))
        import local_mihari

        class HTTPRunner:
            def __init__(self, *_args):
                pass

            def call(self, label, prompt, **kwargs):
                body = {
                    "engine": "native",
                    "path": "mihari",
                    "prompt": prompt,
                    "schema": kwargs.get("schema"),
                    "capability": poc.capability("mihari"),
                }
                result = list(poc.request_stream(18781, body, "mihari"))[-1]
                return {
                    "returncode": 0 if result["success"] else 1,
                    "is_error": not result["success"],
                    "result": result.get("text"),
                    "session_id": result.get("session_id"),
                    "structured_output": result.get("structured_output"),
                }

        local_mihari.NativeRunner = HTTPRunner
        sys.argv = ["local_mihari.py", "--runtime", str(a.runtime / "actual-mihari")]
        local_mihari.main()


if __name__ == "__main__":
    main()
