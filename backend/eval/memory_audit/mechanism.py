"""Profile a read-only counterpart of the release parser's tool-result scan."""

import argparse
from pathlib import Path

from psycopg import sql

from .lab import Lab
from .public_data import BASELINE, uuid_for, write_private

SIGNATURE = "public.publish_agent_evidence_index(uuid,text,jsonb,jsonb,integer,boolean)"


def relevant_plan(node):
    fields = (
        "Node Type",
        "Parent Relationship",
        "Index Name",
        "Actual Rows",
        "Actual Loops",
        "Rows Removed by Filter",
        "Rows Removed by Join Filter",
        "Actual Total Time",
        "Shared Hit Blocks",
        "Shared Read Blocks",
    )
    return {
        **{field: node[field] for field in fields if field in node},
        "children": [relevant_plan(child) for child in node.get("Plans", [])],
    }


def dedup_predicate(lab):
    definition = lab.pg.execute(
        "SELECT pg_get_functiondef(%s::regprocedure) AS definition", [SIGNATURE]
    ).fetchone()["definition"]
    anchor = "UPDATE public.agent_evidence_events e SET displayable=false"
    start = definition.index(anchor) + len(anchor)
    end = definition.index(";", start)
    return definition[start:end].replace("e.session_id=s.id", "e.session_id=%s::uuid")


def stored_targets(lab, artifact, condition):
    folder = uuid_for(artifact, condition, "repo")
    rows = lab.pg.execute(
        "SELECT id FROM agent_evidence_sessions WHERE folder_id=%s ORDER BY native_session_id",
        [folder],
    ).fetchall()
    return [row["id"] for row in rows]


def measure(lab):
    predicate = dedup_predicate(lab)
    query = sql.SQL(
        "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) "
        "SELECT count(*) FROM public.agent_evidence_events e "
    ) + sql.SQL(predicate)
    groups = [
        ("duplicate_hot", "capacity-replay-4096.jsonl", "one_serial"),
        ("duplicate_spread", "capacity-replay-4096.jsonl", "four_serial"),
        ("messages_hot", "capacity-messages-4096.jsonl", "one_serial"),
        ("unique_result_hot", "capacity-distinct-results-4096.jsonl", "one_serial"),
    ]
    grades = {}
    for key, artifact, condition in groups:
        seen = []
        for sid in stored_targets(lab, artifact, condition):
            rows = lab.pg.execute(
                """SELECT count(*) AS events,
                          count(*) FILTER (WHERE event_type='tool_result') AS tool_results
                   FROM agent_evidence_events WHERE session_id=%s""",
                [sid],
            ).fetchone()
            estimates = next(iter(lab.pg.execute(query, [sid]).fetchone().values()))[0]
            seen.append(
                {
                    **rows,
                    "execution_ms": estimates["Execution Time"],
                    "plan": relevant_plan(estimates["Plan"]),
                }
            )
        grades[key] = seen
    return {
        "baseline": BASELINE,
        "method": "Read-only count with the exact frozen parser's dedup predicate.",
        "parser_updates_executed": False,
        "groups": grades,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lab = Lab(args.lab)
    try:
        result = measure(lab)
        write_private(args.output, result)
        print(f"Measured {len(result['groups'])} reference plan shapes.")
    finally:
        lab.close()


if __name__ == "__main__":
    main()
