"""Reproduce routing, cross-directory resume and bounded-turn protocol probes."""

import argparse
import json
import uuid
from pathlib import Path

from duplex import DuplexSession
from native import NativeRunner
from soak import fixture, mcp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    args = parser.parse_args()
    root = args.runtime.resolve()
    root.mkdir(parents=True, exist_ok=True)
    checks = {}
    sid_a, sid_b = str(uuid.uuid4()), str(uuid.uuid4())
    session = DuplexSession(root / "multiplex", sid_a)
    try:
        first = session.ask(
            "For fictional project invoice-A, we selected Redis Streams as the queue. Acknowledge briefly.",
            timeout=30,
        )
        session.session_id = sid_b
        second = session.ask(
            "Which queue did the user select in this conversation? Answer briefly.",
            timeout=30,
        )
        checks["input_session_id_is_not_a_router"] = {
            "process_session_id": sid_a,
            "other_input_session_id": sid_b,
            "returned_session_id": second["session_id"],
            "other_session_isolated": second["session_id"] == sid_b
            and "Redis" not in (second["result"] or ""),
            "first_result": first["result"],
            "second_result": second["result"],
        }
    except Exception as exc:
        checks["multiplex_error"] = str(exc)
    finally:
        session.close(force=True)
    first_runner = NativeRunner(root / "worker-a")
    second_runner = NativeRunner(root / "worker-b")
    first = first_runner.call(
        "cwd-session-start",
        "For our synthetic notification service we chose Redis Streams and event_id deduplication. Acknowledge.",
        exclude_instructions=True,
        system_prompt="Discuss supplied repository facts concisely.",
    )
    second = second_runner.call(
        "cwd-session-resume",
        "Which queue did we choose?",
        resume=first["session_id"],
        exclude_instructions=True,
        system_prompt="Discuss supplied repository facts concisely.",
    )
    checks["cross_cwd_resume"] = {
        "returncode": second["returncode"],
        "correct": "Redis Streams" in (second["result"] or ""),
        "call_ids": [first["id"], second["id"]],
    }
    repo, _ = fixture(root, "budget-worker", 0)
    limited = first_runner.call(
        "one-turn-tool-budget",
        "Use knowledge_base_search, then code_graph_lookup to explain retryable and its callers. Cite sources.",
        mcp=mcp(repo),
        persist=False,
        max_turns=1,
    )
    fallback = first_runner.call(
        "bounded-fallback-answer",
        "Evidence [1]: src/worker.py defines retryable(status) as status in(429,503). process calls retryable after unsuccessful send. Explain in under50words and cite [1].",
        persist=False,
        system_prompt="Answer from supplied evidence and cite [1].",
    )
    checks["bounded_turn_fallback"] = {
        "limited_returncode": limited["returncode"],
        "limited_subtype": limited["subtype"],
        "fallback_success": fallback["returncode"] == 0,
        "call_ids": [limited["id"], fallback["id"]],
    }
    (root / "checks.json").write_text(json.dumps(checks, indent=2))
    print(json.dumps(checks), flush=True)


if __name__ == "__main__":
    main()
