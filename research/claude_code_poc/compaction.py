"""Bounded large synthetic conversation to observe native compaction behavior."""

import json
from pathlib import Path

from native import NativeRunner


def main():
    root = Path("/private/tmp/kioku-claude-poc-runtime/compaction")
    runner = NativeRunner(root)
    notes = []
    for index in range(1200):
        notes.append(
            f"Historical research item {index}: candidate queue transport candidate-{index} was investigated but NOT adopted. "
            "The test was inconclusive; there was no code change or deployment. "
            "Do not present this candidate as a current repository fact. "
            "Preserve only the final explicit architecture decision given at the end."
        )
    history = "\n".join(notes)
    prompt = (
        history
        + "\nFINAL ADOPTED ARCHITECTURE: PostgreSQL outbox, event_id idempotency, "
        "permanent401/403failures, transient429/503retries. Reply with only a one-sentence summary of the final decision."
    )
    first = runner.call(
        "large-session-before-compaction",
        prompt,
        thinking_tokens=0,
        exclude_instructions=True,
        autocompact="100k",
        timeout=240,
        system_prompt="You are Kioku. Preserve final adopted facts and distinguish inconclusive research from decisions.",
    )
    continuation = "\n".join(
        f"Additional discarded research item {i}: no adoption or deployment occurred; do not replace adopted facts. "
        * 3
        for i in range(350)
    )
    second = runner.call(
        "large-session-compaction-followup",
        continuation
        + "\nWhat is the final adopted architecture and error policy from our earlier conversation? Answer under80words.",
        resume=first.get("session_id"),
        thinking_tokens=0,
        exclude_instructions=True,
        autocompact="100k",
        timeout=240,
        system_prompt="You are Kioku. Preserve final adopted facts and distinguish inconclusive research from decisions.",
    )
    boundaries = []
    for record in [first, second]:
        path = root / record["id"] / "events.jsonl"
        for line in path.read_text().splitlines():
            event = json.loads(line)
            if event.get("type") == "system" and "compact" in event.get("subtype", ""):
                boundaries.append(event)
    checks = {
        "first_call": first["id"],
        "second_call": second["id"],
        "first_prompt_chars": len(prompt),
        "second_prompt_chars": len(continuation),
        "first_success": first["returncode"] == 0,
        "second_success": second["returncode"] == 0,
        "final_fact_retained": "PostgreSQL" in (second.get("result") or "")
        and "event_id" in (second.get("result") or ""),
        "compaction_boundary_count": len(boundaries),
        "compaction_boundaries": boundaries,
        "second_result": second.get("result"),
    }
    (root / "checks.json").write_text(json.dumps(checks, indent=2))
    print(json.dumps(checks), flush=True)


if __name__ == "__main__":
    main()
