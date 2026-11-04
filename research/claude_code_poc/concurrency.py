"""Repeat bounded native-process fanout at zero, one, and two hours."""

import concurrent.futures
import json
import time
from pathlib import Path

from native import NativeRunner


def main():
    root = Path("/private/tmp/kioku-claude-poc-runtime/concurrency")
    runner = NativeRunner(root / "calls")
    started = time.monotonic()
    outcomes = []
    schema = {
        "type": "object",
        "properties": {
            "project": {"type": "string"},
            "max_attempts": {"type": "integer"},
        },
        "required": ["project", "max_attempts"],
        "additionalProperties": False,
    }
    for round_index in range(3):
        target = started + round_index * 3600
        while time.monotonic() < target:
            time.sleep(min(30, target - time.monotonic()))
        for model, fanout in [("haiku", 1), ("haiku", 2), ("haiku", 4), ("sonnet", 4)]:
            batch_start = time.monotonic()
            with concurrent.futures.ThreadPoolExecutor(max_workers=fanout) as pool:
                futures = [
                    pool.submit(
                        runner.call,
                        f"hour-{round_index}-{model}-fanout-{fanout}-{index}",
                        f"Supplied source facts: project invoice-{index} sets max_attempts={index + 2}. "
                        "Return those source facts in the required structure.",
                        model=model,
                        persist=False,
                        schema=schema,
                        exclude_instructions=True,
                        system_prompt="Report only supplied source facts.",
                    )
                    for index in range(fanout)
                ]
                rows = [future.result() for future in futures]
            outcomes.append(
                {
                    "hour": round_index,
                    "model": model,
                    "fanout": fanout,
                    "wall_time_s": round(time.monotonic() - batch_start, 3),
                    "successes": sum(
                        row["returncode"] == 0 and not row["is_error"] for row in rows
                    ),
                    "isolation_correct": all(
                        (row.get("structured_output") or {}).get("project")
                        == f"invoice-{index}"
                        and (row.get("structured_output") or {}).get("max_attempts")
                        == index + 2
                        for index, row in enumerate(rows)
                    ),
                    "call_ids": [row["id"] for row in rows],
                }
            )
            (root / "checks.json").write_text(json.dumps(outcomes, indent=2))
            print(json.dumps(outcomes[-1]), flush=True)


if __name__ == "__main__":
    main()
