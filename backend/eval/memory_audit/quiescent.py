"""Repeat a fixed read-only discovery shape after all lab indexing stops."""

import argparse
import json
from pathlib import Path

from .lab import Lab
from .public_data import BASELINE, file_sha256, stable_priority, write_private
from .score_public import distribution
from .sentinels import timed_search


def server_state(lab):
    connections = lab.pg.execute(
        """SELECT count(*) FILTER (WHERE state='active') AS active_other_backends,
                  count(*) AS other_backends
           FROM pg_stat_activity
           WHERE datname=current_database() AND pid<>pg_backend_pid()
             AND backend_type='client backend'"""
    ).fetchone()
    archive = lab.pg.execute(
        """SELECT (SELECT count(*) FROM agent_evidence_sessions) AS sessions,
                  (SELECT count(*) FROM agent_evidence_events) AS stored_records,
                  (SELECT count(*) FROM agent_memory_chunks) AS searchable_chunks"""
    ).fetchone()
    return {**connections, **archive}


def fixed_cases(directories):
    cases = {}
    for directory in directories:
        manifest = json.loads((directory / "freeze.json").read_text())
        path = directory / "queries.json"
        if (
            manifest["baseline"] != BASELINE
            or file_sha256(path) != manifest["sha256"]["queries.json"]
        ):
            raise ValueError("Quiescent case manifests must use the frozen inputs")
        for case in json.loads(path.read_text()):
            family = case["family"]
            priority = stable_priority(case["case_id"])
            if family not in cases or priority < cases[family][0]:
                cases[family] = (priority, case)
    return [case for _, case in sorted(cases.values(), key=lambda item: item[0])]


def run(lab, directories):
    cases = fixed_cases(directories)
    initial = server_state(lab)
    if initial["active_other_backends"]:
        raise RuntimeError("Wait for active audit workers to finish before quiescent measurement")
    samples = {}
    for case in cases:
        with lab.tools(case["owner"], case["root"]) as tool:
            timed_search(tool, lab, case, 10)  # unscored warm-up
            measurements = [timed_search(tool, lab, case, 10) for _ in range(5)]
        samples[case["family"]] = {
            "case_id": case["case_id"],
            "latency_ms": distribution(row["ms"] for row in measurements),
            "postgres_rpc_wall_ms": distribution(row["rpc_ms"] for row in measurements),
            "status_codes": [row["code"] for row in measurements],
            "distinct_ranking_fingerprints": len({tuple(row["events"]) for row in measurements}),
        }
    final = server_state(lab)
    return {
        "baseline": BASELINE,
        "postgres_version": lab.pg.info.server_version,
        "boundary": "colocated direct MCP callable, relevance, ten results, no expansions",
        "before": initial,
        "after": final,
        "samples": samples,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, required=True)
    parser.add_argument("--frozen", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lab = Lab(args.lab)
    try:
        summary = run(lab, args.frozen)
        write_private(args.output, summary)
        print(f"Repeated five warm calls in each of {len(summary['samples'])} dataset scopes.")
    finally:
        lab.close()


if __name__ == "__main__":
    main()
