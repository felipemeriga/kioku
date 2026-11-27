"""Exercise the normal evidence worker with temporary lab connection timeouts."""

import argparse
import time
from pathlib import Path

import psycopg

from services.agent_evidence import EvidenceStore
from services.agent_evidence_models import sha256

from .lab import Lab
from .liveness import drain, seed, verify_drain
from .public_data import BASELINE, uuid_for, write_private

TIMEOUTS = {"lock_timeout": "1s", "statement_timeout": "5s"}


def function_timeout_boundary(lab):
    before = lab.pg.execute("SHOW statement_timeout").fetchone()["statement_timeout"]
    lab.pg.execute("CREATE TEMP TABLE timer_namespace (id integer)")
    lab.pg.execute("""
        CREATE FUNCTION pg_temp.audit_timeout_probe() RETURNS integer LANGUAGE plpgsql
        SET statement_timeout TO '1ms'
        AS $$ BEGIN PERFORM pg_sleep(0.05); RETURN 1; END $$;
    """)
    outcomes = {}
    try:
        for name, outer_budget in (("inherited_outer", before), ("five_ms_outer", "5ms")):
            lab.pg.execute("SELECT set_config('statement_timeout',%s,false)", [outer_budget])
            start = time.perf_counter()
            code = None
            try:
                lab.pg.execute("SELECT pg_temp.audit_timeout_probe()").fetchone()
            except psycopg.Error as exc:
                code = exc.sqlstate
            outcomes[name] = {
                "outer_budget": outer_budget,
                "sqlstate": code,
                "elapsed_ms": (time.perf_counter() - start) * 1000,
            }
    finally:
        lab.pg.execute("SELECT set_config('statement_timeout',%s,false)", [before])
    return {"temporary_inner_budget": "1ms", "sleep_ms": 50, "observations": outcomes}


def verify_every_segment(lab, targets, expected):
    count = 0
    with lab.service_role():
        for session in targets:
            store = EvidenceStore(lab, session["user_id"], session["folder_id"])
            value = store.session(session["id"])
            for segment in value["manifest_json"]["segments"]:
                obj = store.object(session["id"], segment["id"])
                if sha256(store.download(obj)) == segment["sha256"]:
                    count += 1
    return {"sha256_verified": count, "expected": expected}


def run(lab, lab_file, output):
    owner, root, folder = (uuid_for(output.name, part) for part in ("owner", "root", "repo"))
    lab.create_owner(owner)
    lab.create_folder(root, owner, "timeout-control")
    lab.create_folder(folder, owner, "timeout-recovery", root)
    segments, rows_per_segment = 64, 64
    targets = seed(lab, owner, folder, 1, segments, rows_per_segment, "duplicate_results")
    initial = lab.index_state(owner, folder)
    constrained = drain(
        lab,
        lab_file,
        owner,
        folder,
        targets,
        "one_overlap",
        120,
        settings=TIMEOUTS,
    )
    # Each additional worker connection starts with the normal lab settings.
    # Recovery works from unchanged committed originals and remaining work.
    restored = drain(lab, lab_file, owner, folder, targets, "one_serial", 420)
    final = lab.index_state(owner, folder)
    verification = verify_every_segment(lab, targets, segments)
    manifest_valid = None
    repeat_state_unchanged = None
    if restored["fully_indexed"]:
        manifest_valid = verify_drain(lab, targets)
        repeat_state_unchanged = lab.index_state(owner, folder) == final
    return {
        "baseline": BASELINE,
        "per_connection_timeouts": TIMEOUTS,
        "lab_defaults_restored_by_separate_connection": True,
        "committed_source_records": segments * rows_per_segment,
        "initial": initial,
        "constrained": constrained,
        "restored": restored,
        "originals": verification,
        "manifest_valid": manifest_valid,
        "repeat_state_unchanged": repeat_state_unchanged,
        "timeout_boundary": function_timeout_boundary(lab),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lab = Lab(args.lab)
    try:
        result = run(lab, args.lab, args.output)
        write_private(args.output, result)
        print("Replayed the bounded timeout workload and recovery.")
    finally:
        lab.close()


if __name__ == "__main__":
    main()
