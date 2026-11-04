"""Resume a prior synthetic conversation after replacing the container."""

import argparse
import json
from pathlib import Path

from native import NativeRunner


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    args = parser.parse_args()
    rows = [
        json.loads(line)
        for line in (args.runtime / "calls/calls.jsonl").read_text().splitlines()
    ]
    initial = next(row for row in rows if row["label"] == "server-chat")
    row = NativeRunner(args.runtime / "calls").call(
        "container-recreated-resume",
        "What database pattern and idempotency key did we select earlier?",
        resume=initial["session_id"],
        system_prompt="You are Kioku. Answer using prior conversation facts.",
    )
    result = {
        "passed": row["returncode"] == 0
        and "PostgreSQL" in row["result"]
        and "event_id" in row["result"],
        "session_preserved": row["session_id"] == initial["session_id"],
        "elapsed_s": row["elapsed_s"],
        "result": row["result"],
    }
    (args.runtime / "restart-result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
