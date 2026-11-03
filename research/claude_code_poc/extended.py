"""Deeper one-shot scenarios supplementing the real-time soak."""

import concurrent.futures
import json
import time
import uuid
from pathlib import Path

from native import NativeRunner
from soak import fixture, mcp


def main():
    root = Path("/private/tmp/kioku-claude-poc-runtime/extended")
    runner = NativeRunner(root)
    checks = []

    def note(name, passed, records, **details):
        checks.append(
            {
                "name": name,
                "passed": passed,
                "call_ids": [r["id"] for r in records],
                **details,
            }
        )
        (root / "checks.json").write_text(json.dumps(checks, indent=2))
        print(json.dumps(checks[-1]), flush=True)

    question = "Explain why event_id makes invoice retries idempotent in two concise sentences."
    default = runner.call("default-system-overhead", question, persist=False)
    minimal = runner.call(
        "minimal-system-overhead",
        question,
        persist=False,
        system_prompt="You are Kioku, a concise repository research assistant. Ground facts in supplied context.",
    )
    note(
        "system-prompt-comparison",
        all(r["returncode"] == 0 for r in [default, minimal]),
        [default, minimal],
    )

    schema = {
        "type": "object",
        "properties": {
            "max_attempts": {"type": "integer"},
            "deployment_confirmed": {"type": "boolean"},
            "source": {"type": "string"},
        },
        "required": ["max_attempts", "deployment_confirmed", "source"],
        "additionalProperties": False,
    }
    structured = runner.call(
        "structured-maintenance-output",
        "Source worker.py sets MAX_ATTEMPTS=7. No deployment evidence was provided. "
        "Return the structured facts, naming worker.py as source.",
        persist=False,
        schema=schema,
    )
    output = structured.get("structured_output") or {}
    note(
        "schema-validation",
        output.get("max_attempts") == 7 and output.get("deployment_confirmed") is False,
        [structured],
    )

    history = []
    for index in range(100):
        history.append(
            f"Turn {index}: We investigated queue option candidate-{index}, but this was exploratory and not adopted. "
            "Retry design must distinguish transient and permanent errors. Deployment remains unconfirmed. "
            * 4
        )
    history.append(
        "FINAL ADOPTED DECISION: PostgreSQL outbox. event_id is the idempotency key. "
        "All earlier candidate options were rejected."
    )
    long_prompt = (
        "Conversation history:\n"
        + "\n".join(history)
        + "\nQuestion: What queue is currently adopted? Answer one sentence."
    )
    for model in ["haiku", "sonnet"]:
        result = runner.call(
            f"long-explicit-history-{model}", long_prompt, persist=False, model=model
        )
        note(
            f"long-history-{model}",
            "PostgreSQL outbox" in (result["result"] or ""),
            [result],
            history_chars=len(long_prompt),
        )

    session_id = str(uuid.uuid4())
    initial = runner.call(
        "collision-session-initial",
        "We selected the invoice queue. Acknowledge briefly.",
        session_id=session_id,
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                runner.call,
                f"same-session-concurrent-{index}",
                "Describe the queue decision in at most three sentences.",
                resume=session_id,
            )
            for index in range(2)
        ]
        collisions = [f.result() for f in futures]
    recovery = runner.call(
        "same-session-after-collision",
        "What topic have we discussed? Answer briefly.",
        resume=session_id,
    )
    note(
        "same-session-concurrency",
        recovery["returncode"] == 0,
        [initial, *collisions, recovery],
        collision_returncodes=[r["returncode"] for r in collisions],
    )

    ephemeral_id = str(uuid.uuid4())
    ephemeral = runner.call(
        "ephemeral-explicit-session",
        "Our fixture storage is PostgreSQL. Acknowledge.",
        session_id=ephemeral_id,
        persist=False,
    )
    missing = runner.call(
        "resume-ephemeral-session",
        "What storage did we choose?",
        resume=ephemeral_id,
        timeout=30,
    )
    note(
        "no-persistence-cannot-resume", missing["returncode"] != 0, [ephemeral, missing]
    )

    repo, _ = fixture(root, "reuse-fixture", 0)
    first = runner.call(
        "repo-reuse-initial",
        "Use knowledge_base_search. What is MAX_ATTEMPTS now? Cite the source.",
        mcp=mcp(repo),
    )
    repo, expected = fixture(root, "reuse-fixture", 4)
    updated = runner.call(
        "repo-reuse-after-source-change",
        "The source has changed. Use knowledge_base_search again, do not rely on earlier content. "
        "What is MAX_ATTEMPTS now? Cite the source.",
        resume=first.get("session_id"),
        mcp=mcp(repo),
    )
    note(
        "repo-session-refresh",
        str(expected) in (updated["result"] or ""),
        [first, updated],
    )

    persisted_id = str(uuid.uuid4())
    interrupted = runner.call(
        "interrupt-mid-generation",
        "Write an extensive fictional architecture guide for a queue service.",
        session_id=persisted_id,
        kill_after=2.5,
    )
    resumed = runner.call(
        "resume-after-interruption",
        "The previous turn was interrupted. Reply with RECOVERY_OK and one sentence about the topic.",
        resume=persisted_id,
        timeout=60,
    )
    note(
        "interrupted-session-recovery",
        resumed["returncode"] == 0,
        [interrupted, resumed],
    )
    print(
        json.dumps(
            {
                "status": "completed",
                "checks": len(checks),
                "finished_epoch": time.time(),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
