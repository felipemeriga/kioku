"""Compare a private scalar-tsquery prototype against the frozen search function."""

import argparse
import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import psycopg

from services import agent_memory

from .candidate_diagnostic import query_manifest
from .lab import Lab
from .mechanism import MEMORY_SQL, collect_nested_plans
from .operational import AuditClock
from .public_data import BASELINE, file_sha256, json_text, stable_priority, uuid_for, write_private
from .quiescent import fixed_cases, server_state
from .replay import code, log_line, open_output
from .score_public import distribution

SEARCH = "search_agent_memory_v2"
CANDIDATE = "kioku_audit_search_scalar_v2"
CANDIDATE_SIGNATURE = MEMORY_SQL.replace(SEARCH, CANDIDATE)
ABBA = ("A", "B", "B", "A")
ORDER_LIMITS = (("literal", "relevance", 50), ("default", "chronological", 10))
CAP_NAMESPACE = "scalar-search-scope-cap"
EXPECTED_EDGE = {
    "instant-cutoff": ("ok", 1),
    "scope-foreign": ("memory_folder_not_found_or_ambiguous", None),
    "scope-cap-100": ("ok", 0),
    "scope-cap-101": ("scope_too_broad", None),
    "scope-cap-101-named": ("scope_too_broad", None),
    "rare-id": ("ok", 1),
    "absent-id": ("ok", 0),
    "invalid-offset": ("invalid_pagination", None),
    "invalid-limit": ("invalid_pagination", None),
}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def installed_definition(lab):
    return lab.pg.execute(
        "SELECT pg_get_functiondef(%s::regprocedure) AS definition", [MEMORY_SQL]
    ).fetchone()["definition"]


def candidate_definition(original):
    declaration = f"CREATE OR REPLACE FUNCTION public.{SEARCH}("
    variable = "DECLARE result jsonb;"
    terms_start = "WITH terms AS MATERIALIZED"
    query_start = "), query AS ("
    matched_start = "), matched AS MATERIALIZED"
    for marker in (
        declaration,
        variable,
        terms_start,
        query_start,
        matched_start,
        "CROSS JOIN query",
    ):
        if original.count(marker) != 1:
            raise ValueError(f"Unexpected frozen SQL shape around {marker}")
    if original.count("query.q") != 4:
        raise ValueError("Unexpected frozen tsquery references")
    start = original.index(terms_start)
    middle = original.index(query_start, start)
    end = original.index(matched_start, middle)
    terms = original[start : middle + 1]
    aggregate = original[middle + len(query_start) : end].strip()
    before, marker, after = aggregate.partition(" END q")
    if not marker or not after.strip().startswith("FROM terms"):
        raise ValueError("The frozen query aggregate no longer ends in one scalar projection")
    assignment = before + " END INTO recall_query" + after
    scalar_query = ", query AS (\n SELECT recall_query q\n"
    body = (
        original[:start] + terms + "\n" + assignment + ";\n" + terms + scalar_query + original[end:]
    )
    return body.replace(declaration, f"CREATE FUNCTION public.{CANDIDATE}(", 1).replace(
        variable, variable + " recall_query tsquery;", 1
    )


class ScalarLab(Lab):
    """Change only the recalled RPC name and retain actual SQL results in memory."""

    variant = "A"
    observation = None

    def rpc(self, name, args):
        if name != SEARCH:
            return super().rpc(name, args)
        operation = super().rpc(CANDIDATE if self.variant == "B" else SEARCH, args)

        def execute():
            if self.observation is not None:
                raise RuntimeError("Expected one recall RPC per search tool call")
            wall_start = self.db_wall["rpc"]
            try:
                # A statement error must not abort the shared read snapshot.
                with self.pg.transaction():
                    result = operation.execute()
            except psycopg.Error as exc:
                self.observation = {
                    "args": args,
                    "sqlstate": exc.sqlstate,
                    "rpc_ms": (self.db_wall["rpc"] - wall_start) * 1000,
                }
                raise
            else:
                self.observation = {
                    "args": args,
                    "sql": result.data,
                    "rpc_ms": (self.db_wall["rpc"] - wall_start) * 1000,
                }
                return result

        return SimpleNamespace(execute=execute)


def request(identity, owner, scope, query="", **params):
    return {"id": identity, "owner": owner, "scope": scope, "params": {"query": query, **params}}


def public_request(identity, case, **extra):
    return request(
        identity, case["owner"], case["root"], case["question"], **case["filters"], **extra
    )


def edge_cases():
    ops = "operational-frozen-v2"
    owner, root = (uuid_for("operations", ops, part) for part in ("owner", "active"))
    cap_owner = uuid_for("sentinel-results.json", "scope-owner")
    cap_root = uuid_for("sentinel-results.json", "scope-root")
    cap_repo = uuid_for(cap_root, 0)
    stress_owner = uuid_for("capacity-messages-16384.jsonl", "one_serial", "owner")
    stress_repo = uuid_for("capacity-messages-16384.jsonl", "one_serial", "repo")
    zone = "America/New_York"
    broad = "Have we checked the relay checkpoint checksum?"
    activity = ("2026-11-16", "2026-11-22")
    return [
        request(
            "day-range",
            owner,
            root,
            "SSE outage",
            from_date="2026-11-12",
            through_date="2026-11-12",
            timezone=zone,
        ),
        request("day-cutoff", owner, root, "SSE outage", as_of="2026-11-12", timezone=zone),
        request(
            "instant-cutoff",
            owner,
            root,
            "EXACT_CUTOFF",
            as_of="2026-11-21T01:00:00-05:00",
            timezone=zone,
            folder="cedar-client",
        ),
        request(
            "dst-fold-first", owner, root, "DST", as_of="2026-11-01T01:30:00-04:00", timezone=zone
        ),
        request(
            "dst-fold-second", owner, root, "DST", as_of="2026-11-01T01:30:00-05:00", timezone=zone
        ),
        request("scope-named", owner, root, "MAPLE_MIGRATION", folder="spruce-relay"),
        request("scope-foreign", owner, root, "MAPLE_MIGRATION", folder="foreign-relay"),
        request("scope-direct", cap_owner, cap_repo, "nonexistent"),
        request(
            "scope-cap-100",
            uuid_for(CAP_NAMESPACE, "owner"),
            uuid_for(CAP_NAMESPACE, "root"),
            "nonexistent",
        ),
        request("scope-cap-101", cap_owner, cap_root, "nonexistent"),
        request("scope-cap-101-named", cap_owner, cap_root, "nonexistent", folder="scope-child-0"),
        request("empty-latest", owner, root, order="latest"),
        request("empty-chronological", owner, root),
        request(
            "empty-overview",
            owner,
            root,
            projection="overview",
            from_date=activity[0],
            through_date=activity[1],
            timezone=zone,
        ),
        request("punctuation", owner, root, "?!#..."),
        request(
            "session-latest-prefix", stress_owner, stress_repo, order="latest", session="lane-"
        ),
        request(
            "session-latest-exact", stress_owner, stress_repo, order="latest", session="lane-0"
        ),
        request("session-none", stress_owner, stress_repo, "LOAD_ANCHOR_42", session="nonexistent"),
        request("expansions", owner, root, "rebuild", queries=["cached reuse", "incremental"]),
        request("rare-id", stress_owner, stress_repo, "LOAD_ANCHOR_42", order="relevance", limit=1),
        request(
            "absent-id", stress_owner, stress_repo, "NOHITQZ909773", order="relevance", limit=1
        ),
        request(
            "broad-with-id", stress_owner, stress_repo, broad + " LOAD_ANCHOR_42", order="relevance"
        ),
        request(
            "page-cap", stress_owner, stress_repo, broad, order="relevance", offset=10000, limit=50
        ),
        request("invalid-offset", stress_owner, stress_repo, broad, offset=10001),
        request("invalid-limit", stress_owner, stress_repo, broad, limit=51),
        request("invalid-timezone", owner, root, "SSE", timezone="Invalid/Audit_Zone"),
        request(
            "invalid-range", owner, root, "SSE", from_date="2026-11-20", through_date="2026-11-19"
        ),
        request("invalid-session", owner, root, "SSE", session="!invalid"),
        request("invalid-order", owner, root, "SSE", order="unsupported"),
        request("invalid-overview", owner, root, "SSE", projection="overview"),
        request("invalid-as-of", owner, root, "SSE", as_of="2026-11-12T15:00:00"),
        request("invalid-expansions", owner, root, "SSE", queries=["test"] * 9),
        request("too-many-terms", owner, root, " ".join(f"token{i}" for i in range(101))),
    ]


def freeze(initial, extension, beam, output):
    cases = sorted(
        query_manifest([initial, extension]), key=lambda case: stable_priority(case["case_id"])
    )
    requests = [
        public_request(f"{case['case_id']}-{label}", case, order=order, limit=limit)
        for case in cases
        for label, order, limit in ORDER_LIMITS
    ]
    edges = edge_cases()
    by_id = {case["id"]: case for case in edges}
    rare = by_id["rare-id"]
    live_scope = (rare["owner"], rare["scope"])
    performance = [
        rare,
        by_id["absent-id"],
        request(
            "broad-16k",
            *live_scope,
            "Have we checked the relay checkpoint checksum?",
            order="relevance",
            limit=10,
        ),
        public_request("long-small", cases[0], order="relevance", limit=10),
        public_request("beam-10m", fixed_cases([beam])[0], order="relevance", limit=10),
    ]
    plan = {
        "baseline": BASELINE,
        "input_manifest_sha256": [
            file_sha256(path / "freeze.json") for path in (initial, extension, beam)
        ],
        "equivalence": edges + requests,
        "long_mem_pairs": len(requests),
        "edge_pairs": len(edges),
        "expected_edges": EXPECTED_EDGE,
        "wall_clock_guard": "empty-overview uses an independent RPC snapshot_at field",
        "performance": performance,
        "schedule": list(ABBA) * 3,
        "warmup": ["A", "B"],
        "performance_gate": {"selective_median_reduction": 0.2, "other_median_regression": 0.2},
    }
    write_private(output, plan)
    return len(plan["equivalence"])


def trial(lab, mcp, case, variant):
    lab.variant = variant
    lab.observation = None
    started = time.perf_counter()
    result = json.loads(mcp.search_agent_history(**case["params"]))
    wall_ms = (time.perf_counter() - started) * 1000
    sql = lab.observation or {}
    return {
        "variant": variant,
        "tool": result,
        "sql": sql.get("sql"),
        "args": sql.get("args"),
        "sqlstate": sql.get("sqlstate"),
        "wall_ms": wall_ms,
        "rpc_ms": sql.get("rpc_ms"),
    }


def fingerprints(row):
    return {key: digest(json_text(row[key])) for key in ("tool", "sql", "args", "sqlstate")}


def summarize(row):
    return {
        "variant": row["variant"],
        "status": code(row["tool"]),
        "total_matches": row["tool"].get("total_matches"),
        "returned": len(row["tool"].get("matches", [])),
        "rpc_called": row["args"] is not None,
        "wall_ms": row["wall_ms"],
        "rpc_ms": row["rpc_ms"],
        "fingerprints": fingerprints(row),
    }


def different_only_in_match_order(a, b):
    for surface in ("tool", "sql"):
        left, right = a[surface], b[surface]
        if left == right:
            continue
        if not isinstance(left, dict) or not isinstance(right, dict):
            return False
        if {k: v for k, v in left.items() if k != "matches"} != {
            k: v for k, v in right.items() if k != "matches"
        }:
            return False
        if Counter(map(json_text, left.get("matches", []))) != Counter(
            map(json_text, right.get("matches", []))
        ):
            return False
    return a["args"] == b["args"] and a["sqlstate"] == b["sqlstate"]


def differing_fields(left, right):
    if left == right:
        return []
    if not isinstance(left, dict) or not isinstance(right, dict):
        return ["root"]
    missing = object()
    return sorted(
        key
        for key in left.keys() | right.keys()
        if left.get(key, missing) != right.get(key, missing)
    )


def match_differences(left, right):
    a, b = ((value or {}).get("matches", []) for value in (left, right))
    a_ids = [row.get("event_id") for row in a]
    b_ids = [row.get("event_id") for row in b]
    return {
        "same_event_ids_in_order": a_ids == b_ids,
        "same_event_id_membership": Counter(a_ids) == Counter(b_ids),
        "first_differing_match": next(
            (
                {"index": index, "fields": differing_fields(x, y)}
                for index, (x, y) in enumerate(zip(a, b, strict=False))
                if x != y
            ),
            None,
        ),
    }


def paired(lab, case):
    with lab.tools(case["owner"], case["scope"]) as mcp:
        variants = "AB" if int(stable_priority(case["id"]), 16) % 2 else "BA"
        rows = {variant: trial(lab, mcp, case, variant) for variant in variants}
        a, b = rows["A"], rows["B"]
        exact = fingerprints(a) == fingerprints(b)
        difference = None
        if not exact:
            again = {variant: trial(lab, mcp, case, variant) for variant in variants}
            fields = {
                surface: differing_fields(a[surface], b[surface]) for surface in ("tool", "sql")
            }
            if (
                case["id"] == "empty-overview"
                and a["args"] is None
                and b["args"] is None
                and code(a["tool"]) == code(b["tool"]) == "ok"
                and fields == {"tool": ["snapshot_at"], "sql": []}
                and all(
                    set(differing_fields(rows[variant]["tool"], again[variant]["tool"]))
                    <= {"snapshot_at"}
                    for variant in variants
                )
            ):
                kind = "above_sql_wall_clock"
            else:
                kind = "order_only" if different_only_in_match_order(a, b) else "material"
            difference = {
                "kind": kind,
                "same_variant_repeat_equal": {
                    variant: fingerprints(rows[variant]) == fingerprints(again[variant])
                    for variant in variants
                },
                "repeat": {variant: summarize(row) for variant, row in again.items()},
                "different_fields": fields,
                "match_details": {
                    surface: match_differences(a[surface], b[surface])
                    for surface in ("tool", "sql")
                    if isinstance(a[surface], (dict, type(None)))
                    and isinstance(b[surface], (dict, type(None)))
                },
            }
    return {
        "record_type": "pair",
        "id": case["id"],
        "exact": exact,
        "responses": {variant: summarize(row) for variant, row in rows.items()},
        "difference": difference,
    }


def time_case(lab, case, schedule, warmup):
    with lab.tools(case["owner"], case["scope"]) as mcp:
        for variant in warmup:
            trial(lab, mcp, case, variant)
        rows = [summarize(trial(lab, mcp, case, variant)) for variant in schedule]
    return {
        "record_type": "timing",
        "id": case["id"],
        "samples": rows,
        "summary": {
            variant: {
                "wall_ms": distribution(r["wall_ms"] for r in rows if r["variant"] == variant),
                "rpc_ms": distribution(
                    r["rpc_ms"] for r in rows if r["variant"] == variant and r["rpc_ms"] is not None
                ),
            }
            for variant in "AB"
        },
    }


def measure_plans(lab, cases, stream):
    observations = collect_nested_plans(
        lab, "WITH terms AS MATERIALIZED", contains="matched AS MATERIALIZED"
    )
    for case in cases:
        with lab.tools(case["owner"], case["scope"]) as mcp:
            for variant in "AB":
                observations.clear()
                row = summarize(trial(lab, mcp, case, variant))
                if len(observations) != 1:
                    raise RuntimeError("Expected the full nested match/rank SQL in the plan sample")
                log_line(
                    stream, {"record_type": "plan", "id": case["id"], **row, **observations[0]}
                )


def cap_fixture(lab):
    owner, root = (uuid_for(CAP_NAMESPACE, key) for key in ("owner", "root"))
    lab.create_owner(owner)
    lab.create_folder(root, owner, "scalar-test-cap")
    for i in range(99):
        lab.create_folder(uuid_for(root, i), owner, f"scalar-cap-child-{i}", root)


def timing_gate(timings, thresholds):
    factors = {}
    for timing in timings:
        if any(trial["status"] != "ok" or trial["rpc_ms"] is None for trial in timing["samples"]):
            return {"passes": False, "reason": "at_least_one_failed_timing_request"}
        if len({json_text(trial["fingerprints"]) for trial in timing["samples"]}) != 1:
            return {"passes": False, "reason": "timed_output_differed"}
        p50 = timing["summary"]
        factors[timing["id"]] = p50["B"]["rpc_ms"]["p50"] / p50["A"]["rpc_ms"]["p50"]
    selective = 1 - thresholds["selective_median_reduction"]
    other = 1 + thresholds["other_median_regression"]
    passes = all(
        ratio <= (selective if key in {"rare-id", "absent-id"} else other)
        for key, ratio in factors.items()
    )
    return {"passes": passes, "rpc_median_b_over_a": factors}


def run(lab, plan, sha, output):
    start = server_state(lab)
    if start["active_other_backends"]:
        raise RuntimeError("Wait for other lab callers to finish")
    original = installed_definition(lab)
    replacement = candidate_definition(original)
    with open_output(output) as stream:
        log_line(
            stream,
            {
                "record_type": "header",
                "baseline": BASELINE,
                "plan_sha256": sha,
                "original_definition_sha256": digest(original),
                "candidate_definition_sha256": digest(replacement),
                "database": start,
                "snapshot": "one REPEATABLE READ transaction, rolled back",
                "fixed_python_clock": "search.reference_time",
            },
        )
        counts = Counter()
        coverage = {"search_rpc": Counter(), "above_sql": Counter()}
        statuses = {variant: Counter() for variant in "AB"}
        timings = []
        with (
            lab.pg.transaction(force_rollback=True),
            patch.object(agent_memory, "datetime", AuditClock),
        ):
            lab.pg.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            lab.pg.execute(replacement)
            lab.pg.execute(f"REVOKE ALL ON FUNCTION {CANDIDATE_SIGNATURE} FROM PUBLIC")
            lab.pg.execute(f"GRANT EXECUTE ON FUNCTION {CANDIDATE_SIGNATURE} TO service_role")
            cap_fixture(lab)
            for index, case in enumerate(plan["equivalence"], 1):
                pair = paired(lab, case)
                expected = plan["expected_edges"].get(case["id"])
                if expected:
                    pair["expected_status_and_matches"] = expected
                    pair["fixture_expectation_met"] = all(
                        (response["status"], response["total_matches"]) == tuple(expected)
                        for response in pair["responses"].values()
                    )
                elif index > plan["edge_pairs"]:
                    pair["fixture_expectation_met"] = all(
                        response["status"] == "ok" and response["rpc_called"]
                        for response in pair["responses"].values()
                    )
                log_line(stream, pair)
                classification = "exact" if pair["exact"] else pair["difference"]["kind"]
                counts[classification] += 1
                boundary = (
                    "search_rpc"
                    if any(response["rpc_called"] for response in pair["responses"].values())
                    else "above_sql"
                )
                coverage[boundary][classification] += 1
                for variant, response in pair["responses"].items():
                    statuses[variant][response["status"]] += 1
                if classification not in {"exact", "above_sql_wall_clock"} or not pair.get(
                    "fixture_expectation_met", True
                ):
                    if not pair.get("fixture_expectation_met", True):
                        counts["fixture_failure"] += 1
                    print(f"Stopped at the failed comparison gate after pair {index}.", flush=True)
                    break
                if index % 100 == 0:
                    print(f"Compared {index} paired search results.", flush=True)
            gate = not counts["fixture_failure"] and counts["exact"] + counts[
                "above_sql_wall_clock"
            ] == len(plan["equivalence"])
            if gate:
                for case in plan["performance"]:
                    timing = time_case(lab, case, plan["schedule"], plan["warmup"])
                    log_line(stream, timing)
                    timings.append(timing)
                measure_plans(lab, plan["performance"], stream)
        definition_unchanged = installed_definition(lab) == original
        candidate_absent = lab.pg.execute(
            "SELECT to_regprocedure(%s) IS NULL AS absent", [CANDIDATE_SIGNATURE]
        ).fetchone()["absent"]
        log_line(
            stream,
            {
                "record_type": "completion",
                "counts": dict(counts),
                "planned_pairs": len(plan["equivalence"]),
                "tool_statuses": {variant: dict(values) for variant, values in statuses.items()},
                "coverage": {boundary: dict(values) for boundary, values in coverage.items()},
                "exact_search_equivalence_and_guards_gate": gate,
                "performance_gate": timing_gate(timings, plan["performance_gate"])
                if timings
                else None,
                "baseline_unchanged": definition_unchanged,
                "candidate_rolled_back": candidate_absent,
                "database": server_state(lab),
            },
        )
        if not definition_unchanged or not candidate_absent:
            raise RuntimeError("The scratch candidate did not roll back safely")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("freeze", "run"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--sha256")
    parser.add_argument("--initial", type=Path)
    parser.add_argument("--extension", type=Path)
    parser.add_argument("--beam", type=Path)
    parser.add_argument("--lab", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.phase == "freeze":
        count = freeze(args.initial, args.extension, args.beam, args.plan)
        print(f"Froze {count} paired search requests.")
        return
    sha = file_sha256(args.plan)
    plan = json.loads(args.plan.read_text())
    if sha != args.sha256 or plan["baseline"] != BASELINE:
        raise ValueError("The comparison plan is no longer the sealed baseline")
    lab = ScalarLab(args.lab)
    try:
        run(lab, plan, sha, args.output)
    finally:
        lab.close()


if __name__ == "__main__":
    main()
