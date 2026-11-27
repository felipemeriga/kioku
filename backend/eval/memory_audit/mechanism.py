"""Inspect frozen recall and publication query plans in the disposable audit lab."""

import argparse
import json
import re
import time
from pathlib import Path

from psycopg import sql

from services.agent_memory import bounds, lexical_terms, technical_terms

from .lab import Lab
from .public_data import BASELINE, uuid_for, write_private
from .replay import code

SIGNATURE = "public.publish_agent_evidence_index(uuid,text,jsonb,jsonb,integer,boolean)"
MEMORY_SQL = (
    "public.search_agent_memory_v2"
    "(uuid,uuid[],text[],timestamptz,timestamptz,text,text,integer,integer,text[],text)"
)


def relevant_plan(node):
    fields = (
        "Node Type",
        "Parent Relationship",
        "Index Name",
        "Relation Name",
        "Alias",
        "Subplan Name",
        "CTE Name",
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
        "FTS Predicates": [
            field
            for field in ("Filter", "Join Filter", "Index Cond", "Recheck Cond")
            if "@@" in node.get(field, "")
        ],
        "children": [relevant_plan(child) for child in node.get("Plans", [])],
    }


def collect_nested_plans(lab, statement_prefix):
    lab.pg.execute("LOAD 'auto_explain'")
    settings = {
        "client_min_messages": "notice",
        "auto_explain.log_level": "notice",
        "auto_explain.log_min_duration": "0ms",
        "auto_explain.log_nested_statements": "on",
        "auto_explain.log_analyze": "on",
        "auto_explain.log_buffers": "on",
        "auto_explain.log_format": "json",
        "auto_explain.log_parameter_max_length": "0",
    }
    for name, value in settings.items():
        lab.pg.execute("SELECT set_config(%s,%s,false)", [name, value])
    observations = []

    def notice(message):
        head, separator, plan_text = (message.message_primary or "").partition("plan:\n")
        if not separator:
            return
        plan = json.loads(plan_text)
        if isinstance(plan, list):
            plan = plan[0]
        if plan.get("Query Text", "").lstrip().startswith(statement_prefix):
            observations.append(
                {"notice_duration": head.strip(), "statement_plan": relevant_plan(plan["Plan"])}
            )

    lab.pg.add_notice_handler(notice)
    return observations


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


def candidate_prefix(lab):
    definition = lab.pg.execute(
        "SELECT pg_get_functiondef(%s::regprocedure) AS definition", [MEMORY_SQL]
    ).fetchone()["definition"]
    prefix = definition[
        definition.index("WITH terms AS MATERIALIZED") : definition.index(
            ", events AS MATERIALIZED"
        )
    ]
    types = {
        "p_terms": "text[]",
        "p_identifiers": "text[]",
        "p_user_id": "uuid",
        "p_folder_ids": "uuid[]",
        "p_after": "timestamptz",
        "p_before": "timestamptz",
        "p_session": "text",
    }
    prefix = re.sub(
        r"\bp_[a-z_]+\b",
        lambda match: f"%({match[0]})s::{types[match[0]]}",
        prefix,
    )
    return sql.SQL(prefix)


def candidate_parameters(owner, folder, question, after=None, before=None):
    identifiers = technical_terms(question)
    return {
        "p_terms": sorted(set([*lexical_terms([question]), *identifiers])),
        "p_identifiers": identifiers,
        "p_user_id": owner,
        "p_folder_ids": [folder],
        "p_after": after,
        "p_before": before,
        "p_session": None,
    }


def candidate_counter(lab):
    return candidate_prefix(lab) + sql.SQL("""
        SELECT (SELECT count(*) FROM matched) AS pre_focus_chunks,
               (SELECT count(*) FROM focused) AS post_focus_chunks
    """)


def memory_query_shape(lab):
    artifact = "capacity-messages-16384.jsonl"
    owner = uuid_for(artifact, "one_serial", "owner")
    folder = uuid_for(artifact, "one_serial", "repo")
    availability = lab.index_state(owner, folder)
    if availability["indexed_segments"] < 64:
        return {"status": "source_not_fully_indexed", "availability": availability}
    broad = "Have we checked the relay checkpoint checksum?"
    after, before = bounds("2026-12-03", "2026-12-03")
    modes = {
        "broad": (broad, None, None),
        "broad_with_identifier": (broad + " LOAD_ANCHOR_42", None, None),
        "identifier_only": ("LOAD_ANCHOR_42", None, None),
        "last_date": (broad, after, before),
    }
    counter = candidate_counter(lab)
    data = {}
    for key, (question, lower, upper) in modes.items():
        params = candidate_parameters(owner, folder, question, lower, upper)
        rows = lab.pg.execute(counter, params).fetchone()
        plan = lab.pg.execute(
            sql.SQL("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ") + counter, params
        ).fetchone()
        details = next(iter(plan.values()))[0]
        data[key] = {
            **rows,
            "count_query_execution_ms": details["Execution Time"],
            "count_query_plan": relevant_plan(details["Plan"]),
        }
    with lab.tools(owner, folder) as mcp:
        last = json.loads(
            mcp.search_agent_history(broad, order="relevance", limit=50, offset=10000)
        )
        subsequent = json.loads(
            mcp.search_agent_history(
                broad,
                order="relevance",
                limit=50,
                offset=last["next_offset"],
            )
        )
    paging = {
        "last_valid_offset": 10000,
        "returned": len(last["matches"]),
        "total_matches": last["total_matches"],
        "has_more": last["has_more"],
        "next_offset": last["next_offset"],
        "next_offset_error": subsequent.get("detail", {}).get("code"),
    }
    return {"status": "ok", "availability": availability, "queries": data, "pagination": paging}


def inspect_search(lab):
    artifact = "capacity-messages-16384.jsonl"
    owner = uuid_for(artifact, "one_serial", "owner")
    folder = uuid_for(artifact, "one_serial", "repo")
    initial = lab.index_state(owner, folder)
    if initial["indexed_segments"] != 64 or initial["chunks"] != 16384:
        raise ValueError("Nested search inspection requires the full existing 16,384-chunk fixture")
    observations = collect_nested_plans(lab, "WITH terms AS MATERIALIZED")
    broad = "Have we checked the relay checkpoint checksum?"
    queries = {
        "absent_identifier": "NOHITQZ909773",
        "present_identifier": "LOAD_ANCHOR_42",
        "broad": broad,
        "broad_with_identifier": broad + " LOAD_ANCHOR_42",
    }
    attempts = {key: [] for key in queries}
    with lab.tools(owner, folder) as mcp:
        labels = list(queries)
        for trial in range(3):
            for key in labels[trial:] + labels[:trial]:
                observations.clear()
                started = time.perf_counter()
                result = json.loads(
                    mcp.search_agent_history(queries[key], order="relevance", limit=10)
                )
                if len(observations) != 1:
                    raise RuntimeError("Expected one nested search SQL statement per real MCP call")
                attempts[key].append(
                    {
                        "lab_wall_ms": (time.perf_counter() - started) * 1000,
                        "status": code(result),
                        "total_matches": result.get("total_matches"),
                        **observations[0],
                    }
                )
    return {
        "baseline": BASELINE,
        "fixture": artifact,
        "boundary": "actual nested frozen search SQL through the MCP callable, instrumented",
        "initial": initial,
        "final": lab.index_state(owner, folder),
        "attempts": attempts,
    }


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
        "search_candidate_shape": memory_query_shape(lab),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inspect-search", action="store_true")
    args = parser.parse_args()
    lab = Lab(args.lab)
    try:
        result = inspect_search(lab) if args.inspect_search else measure(lab)
        write_private(args.output, result)
        shapes = result["attempts"] if args.inspect_search else result["groups"]
        print(f"Measured {len(shapes)} reference plan shapes.")
    finally:
        lab.close()


if __name__ == "__main__":
    main()
