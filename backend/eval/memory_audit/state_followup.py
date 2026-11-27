"""Replay final-action evidence using the session found by ordinary STATE search."""

import argparse
import json
from pathlib import Path

from .lab import Lab
from .public_data import file_sha256, write_private
from .replay import code, payload, verify_frozen
from .score_public import distribution


def followup(lab, frozen):
    manifest = verify_frozen(frozen, "state_train_replay")
    queries = json.loads((frozen / "queries.json").read_text())
    rows = []
    for case in queries:
        with lab.tools(case["owner"], case["root"]) as mcp:
            first, first_ms, first_bytes = payload(
                mcp.search_agent_history,
                query=case["question"],
                order="relevance",
                limit=10,
                **case["filters"],
            )
            initial = first.get("matches") or []
            row = {
                "case_id": case["case_id"],
                "first_status": code(first),
                "session": None,
                "latest_ids": [],
                "read_ids": [],
                "ms": first_ms,
                "bytes": first_bytes,
                "calls": 1,
            }
            if initial:
                native = initial[0]["native_session_id"]
                latest, latest_ms, latest_bytes = payload(
                    mcp.search_agent_history,
                    query="",
                    order="latest",
                    session=native,
                    limit=10,
                    **case["filters"],
                )
                matches = latest.get("matches") or []
                row.update(
                    {
                        "session": native,
                        "latest_status": code(latest),
                        "latest_ids": [record["event_id"] for record in matches],
                        "ms": first_ms + latest_ms,
                        "bytes": first_bytes + latest_bytes,
                        "calls": 2,
                    }
                )
                result = next(
                    (record for record in matches if record["event_type"] == "tool_result"), None
                )
                if result:
                    expanded, read_ms, read_bytes = payload(
                        mcp.read_agent_evidence,
                        reference=result["reference"],
                        before_records=0,
                        after_records=0,
                        char_limit=4000,
                    )
                    row.update(
                        {
                            "read_status": code(expanded),
                            "read_ids": [
                                record["event_id"] for record in expanded.get("evidence", [])
                            ],
                            "ms": row["ms"] + read_ms,
                            "bytes": row["bytes"] + read_bytes,
                            "calls": 3,
                        }
                    )
            rows.append(row)
    return {"gold_sha256": manifest["sha256"]["gold.json"], "rows": rows}


def score(frozen, raw):
    path = frozen / "gold.json"
    if raw["gold_sha256"] != file_sha256(path):
        raise ValueError("STATE labels changed after freezing")
    gold = json.loads(path.read_text())
    rows = raw["rows"]
    return {
        "cases": len(rows),
        "located_correct_session_at_1": sum(
            [row["session"]] in gold[row["case_id"]]["session_groups"] for row in rows
        ),
        "both_in_latest_since_selected_session": sum(
            all(
                set(group) & set(row["latest_ids"])
                for group in gold[row["case_id"]]["literal_turn_groups"]
            )
            for row in rows
        ),
        "both_in_paired_read": sum(
            all(
                set(group) & set(row["read_ids"])
                for group in gold[row["case_id"]]["literal_turn_groups"]
            )
            for row in rows
        ),
        "component_ms": distribution(row["ms"] for row in rows),
        "component_bytes": distribution(row["bytes"] for row in rows),
        "calls": sum(row["calls"] for row in rows),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("run", "score"))
    parser.add_argument("--frozen", type=Path, required=True)
    parser.add_argument("--lab", type=Path)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    if options.phase == "run":
        lab = Lab(options.lab)
        try:
            write_private(options.output, followup(lab, options.frozen))
            print("Replayed STATE training final-action follow-up.")
        finally:
            lab.close()
    else:
        raw = json.loads(options.replay.read_text())
        write_private(options.output, score(options.frozen, raw))


if __name__ == "__main__":
    main()
