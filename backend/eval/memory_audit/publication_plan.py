"""Measure worker sensitivity to PostgreSQL plan mode in the disposable lab."""

import argparse
import time
from pathlib import Path

from .lab import Lab
from .liveness import drain, seed, verify_drain
from .mechanism import collect_nested_plans, stored_targets
from .public_data import BASELINE, uuid_for, write_private
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


def inspect_publication(lab_file, session, segment, mode):
    lab = Lab(lab_file, application_name="kioku-audit-publication-plan-inspection")
    try:
        lab.pg.execute("SELECT set_config('plan_cache_mode',%s,false)", [mode])
        observations = collect_nested_plans(
            lab, "UPDATE public.agent_evidence_events e SET displayable=false"
        )
        executions = []
        for _ in range(7 if mode == "auto" else 3):
            observations.clear()
            with lab.pg.transaction(force_rollback=True):
                started = time.perf_counter()
                lab.pg.execute(
                    "SELECT public.publish_agent_evidence_index(%s,%s,'[]','{}',1,false)",
                    [session, segment],
                )
                wall_ms = (time.perf_counter() - started) * 1000
            if len(observations) != 1:
                raise RuntimeError("Expected one observed nested deduplication plan")
            executions.append({"lab_wall_ms": wall_ms, **observations[0]})
        return executions
    finally:
        lab.close()


def inspect_completed(lab, lab_file, artifact):
    sessions = stored_targets(lab, artifact, "one_serial")
    if len(sessions) != 1:
        raise ValueError("The inspection requires one completed serial workload")
    session = sessions[0]
    ready = lab.pg.execute(
        """SELECT object_id FROM public.agent_evidence_objects
           WHERE session_id=%s AND kind='segment' AND indexed_parser_version=1
             AND memory_index_version=2 ORDER BY committed_revision""",
        [session],
    ).fetchall()
    if len(ready) != SEGMENTS:
        raise ValueError("The inspection requires the fully indexed synthetic source")
    owner, folder = (uuid_for(artifact, "one_serial", kind) for kind in ("owner", "repo"))
    before = lab.index_state(owner, folder)
    plans = {
        mode: inspect_publication(lab_file, session, ready[0]["object_id"], mode)
        for mode in ("auto", "force_custom_plan", "force_generic_plan")
    }
    return {
        "baseline": BASELINE,
        "artifact": artifact,
        "before": before,
        "after": lab.index_state(owner, folder),
        "writes_rolled_back": True,
        "no_new_records": True,
        "plans": plans,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inspect-completed", help="basename of a completed liveness run")
    args = parser.parse_args()
    lab = Lab(args.lab)
    try:
        if args.inspect_completed:
            write_private(args.output, inspect_completed(lab, args.lab, args.inspect_completed))
            print("Captured actual nested publication plans; all test writes rolled back.")
            return
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
