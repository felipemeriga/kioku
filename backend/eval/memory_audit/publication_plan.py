"""Measure worker sensitivity to PostgreSQL plan mode in the disposable lab."""

import argparse
from pathlib import Path

from .lab import Lab
from .liveness import drain, seed, verify_drain
from .public_data import BASELINE, uuid_for
from .replay import log_line, open_output

SEGMENTS = 64
RECORDS_PER_SEGMENT = 64
STOP_SECONDS = 120
MODES = (
    ("auto", "one_serial"),
    ("force_custom_plan", "one_overlap"),
    ("force_generic_plan", "one_serial"),
    ("force_generic_plan", "one_overlap"),
    ("force_custom_plan", "one_serial"),
    ("auto", "one_overlap"),
)


def relation_statistics(lab):
    return lab.pg.execute("""
        SELECT relname, n_live_tup, n_dead_tup, n_mod_since_analyze,
               analyze_count, autoanalyze_count, last_analyze::text,
               last_autoanalyze::text, pg_relation_size(relid) AS heap_bytes
        FROM pg_stat_user_tables
        WHERE schemaname='public' AND relname IN (
          'agent_evidence_events', 'agent_evidence_objects', 'agent_evidence_sessions'
        )
        ORDER BY relname
    """).fetchall()


def run_mode(lab, lab_file, output, mode, worker_layout):
    owner, root, folder = (
        uuid_for(output.name, mode, worker_layout, kind) for kind in ("owner", "root", "folder")
    )
    lab.create_owner(owner)
    lab.create_folder(root, owner, "publication-plan-control")
    lab.create_folder(folder, owner, "publication-fixture", root)
    targets = seed(lab, owner, folder, 1, SEGMENTS, RECORDS_PER_SEGMENT, "duplicate_results")
    before = relation_statistics(lab)
    result = drain(
        lab,
        lab_file,
        owner,
        folder,
        targets,
        worker_layout,
        STOP_SECONDS,
        settings={"plan_cache_mode": mode},
    )
    after = relation_statistics(lab)
    verified = None
    repeat_state_unchanged = None
    if result["fully_indexed"]:
        complete = lab.index_state(owner, folder)
        verified = verify_drain(lab, targets)
        repeat_state_unchanged = lab.index_state(owner, folder) == complete
    return {
        **result,
        "plan_cache_mode": mode,
        "relation_statistics_before": before,
        "relation_statistics_after": after,
        "boundary_originals_verified": verified,
        "repeat_state_unchanged": repeat_state_unchanged,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lab = Lab(args.lab)
    try:
        with open_output(args.output) as stream:
            log_line(
                stream,
                {
                    "baseline": BASELINE,
                    "segments": SEGMENTS,
                    "records_per_segment": RECORDS_PER_SEGMENT,
                    "postgres_version": lab.pg.info.server_version,
                    "cooperative_stop_seconds": STOP_SECONDS,
                    "mode_order": MODES,
                    "boundary": "normal worker path on isolated lab connections",
                },
            )
            for mode, workers in MODES:
                result = run_mode(lab, args.lab, args.output, mode, workers)
                log_line(stream, result)
                indexed = result["snapshots"][-1]["indexed_segments"]
                print(f"{mode}/{workers}: {indexed}/{SEGMENTS} indexed", flush=True)
    finally:
        lab.close()


if __name__ == "__main__":
    main()
