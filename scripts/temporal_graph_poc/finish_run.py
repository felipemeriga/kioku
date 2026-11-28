"""Guarded unattended durability checks after the frozen long-running trials.

Never restarts production, never marks a goal complete, and never accepts a
missing/failed terminal receipt as permission to restart the isolated graph.
"""

import argparse
import json
import os
import shlex
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from audit_semantics import audit as audit_overlay
from corpus import timestamp
from graph import connect, execute
from recall import graph_facts


def terminal_receipt(path, duration_key, minimum):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if not rows or rows[-1].get("type") != "complete":
        raise ValueError("Study has no terminal receipt")
    terminal = rows[-1]
    if terminal.get("failures") != 0 or terminal.get(duration_key, 0) < minimum:
        raise ValueError("Study failed or duration was not met")
    samples = [r for r in rows if "iteration" in r or "worker" in r]
    reported = terminal.get("iterations", terminal.get("queries"))
    if (
        not samples
        or len(samples) != reported
        or any(r.get("status") != "ok" for r in samples)
    ):
        raise ValueError("Study sample receipts differ from terminal summary")
    return terminal


def study_alive(pid, script_name, output_name):
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        return False
    args = shlex.split(result.stdout.strip())
    return bool(
        len(args) > 1
        and Path(args[0]).name.lower().startswith("python")
        and Path(args[1]).name == script_name
        and any(Path(a).name == output_name for a in args)
    )


def private_json(path, data):
    with os.fdopen(
        os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
    ) as out:
        out.write(json.dumps(data, indent=2) + "\n")


def runtime(container):
    fields = {
        "id": "{{.Id}}",
        "image": "{{.Image}}",
        "started_at": "{{.State.StartedAt}}",
        "project": '{{index .Config.Labels "com.docker.compose.project"}}',
        "running": "{{.State.Running}}",
        "oom": "{{.State.OOMKilled}}",
        "ports": "{{json .NetworkSettings.Ports}}",
    }
    return {
        k: subprocess.check_output(
            ["docker", "inspect", "--format", v, container], text=True
        ).strip()
        for k, v in fields.items()
    }


def verify_runtime(actual, expected):
    if (
        actual["id"] != expected["id"]
        or actual["image"] != expected["image"]
        or actual["project"] != "kioku-c360-temporal-poc"
        or actual["running"] != "true"
        or actual["oom"] != "false"
    ):
        raise ValueError("Runtime is not the healthy isolated experiment")
    ports = json.loads(actual["ports"])
    if any(
        b["HostIp"] != "127.0.0.1"
        for mappings in ports.values()
        if mappings
        for b in mappings
    ):
        raise ValueError("Unexpected non-loopback graph port")


def run(args):
    config = json.loads(args.config.read_text())
    private = Path(config["private_dir"])
    tree = Path(config["worktree"])
    scripts = tree / "scripts/temporal_graph_poc"
    corpus = private / "corpus-v3.sqlite"
    env = private / "neo4j.env"
    revision = config["revision"]
    destination = Path(config["destination"])
    if destination.exists():
        raise ValueError("Durable destination already exists")
    # Bound the idle-sleep assertion to this coordinator, including final audits.
    awake = subprocess.Popen(
        ["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    log = []

    def stage(name, **details):
        item = {"at": datetime.now(UTC).isoformat(), "stage": name, **details}
        log.append(item)
        print(json.dumps(item), flush=True)

    def command(label, script, *parameters):
        with (
            os.fdopen(
                os.open(
                    private / (label + ".stdout.log"),
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                ),
                "w",
            ) as out,
            os.fdopen(
                os.open(
                    private / (label + ".stderr.log"),
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                ),
                "w",
            ) as err,
        ):
            subprocess.run(
                [sys.executable, str(scripts / script), *map(str, parameters)],
                cwd=tree,
                stdout=out,
                stderr=err,
                check=True,
                timeout=240,
            )

    try:
        stage("waiting_for_live_studies", coordinator_pid=os.getpid())
        wait_deadline = time.monotonic() + config.get("max_wait_seconds", 7200)
        while any(
            study_alive(s["pid"], s["script"], s["output"]) for s in config["studies"]
        ):
            if time.monotonic() > wait_deadline:
                raise TimeoutError(
                    "Study processes did not finish within the coordinator budget"
                )
            time.sleep(20)
        receipts = {
            s["output"]: terminal_receipt(
                private / s["output"], s["duration_key"], s["minimum"]
            )
            for s in config["studies"]
        }
        stage("terminal_receipts_verified")
        initial = json.loads(
            (private / "runtime-before-durability-v1.json").read_text()
        )
        before = runtime(config["container"])
        verify_runtime(before, initial)
        command(
            "durability-before-source",
            "audit_graph.py",
            "--corpus",
            corpus,
            "--env-file",
            env,
            "--output",
            private / "durability-before-source.json",
        )
        source_before = json.loads(
            (private / "durability-before-source.json").read_text()
        )
        if (
            source_before["status"] != "ok"
            or source_before["projection_fingerprint"] != config["source_fingerprint"]
        ):
            raise ValueError("Source drift before planned restart")
        overlays_before = {}
        for name, rev in [
            ("frozen", config["frozen_load_revision"]),
            ("latest", revision),
        ]:
            overlays_before[name] = audit_overlay(corpus, env, rev)
            if overlays_before[name]["status"] != "ok":
                raise ValueError("Overlay drift before restart")
        private_json(private / "durability-before-overlays.json", overlays_before)
        # Exclusive marker prevents an accidental second restart on rerun.
        private_json(
            private / "planned-restart-issued.json",
            {"before": before, "at": datetime.now(UTC).isoformat()},
        )
        stage("restarting_isolated_graph")
        subprocess.run(
            ["docker", "restart", "--time", "30", config["container"]],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        deadline = time.monotonic() + 180
        while True:
            try:
                with connect(env) as driver:
                    execute(driver, "RETURN 1 AS ready")
                break
            except Exception:
                if time.monotonic() > deadline:
                    raise
                time.sleep(2)
        after = runtime(config["container"])
        verify_runtime(after, initial)
        if after["started_at"] == before["started_at"]:
            raise ValueError("Restart was not observed")
        stage("graph_restarted")
        # First data query precedes the full scan. OS page cache is not purged.
        db = sqlite3.connect(f"file:{corpus}?mode=ro", uri=True)
        db.row_factory = sqlite3.Row
        case = next(
            c
            for c in json.loads((private / "questions-v1.json").read_text())["cases"]
            if c["id"] == "H04"
        )
        with connect(env) as driver:
            begin = time.perf_counter()
            result = graph_facts(
                driver, db, revision, case["question"], timestamp(case["as_of"]), 8
            )
            first_ms = (time.perf_counter() - begin) * 1000
        if "A07" not in {c["key"] for c in result["claims"]}:
            raise ValueError("Latest recording absent after restart")
        private_json(
            private / "post-restart-first-query.json",
            {
                "case_id": "H04",
                "component_ms": first_ms,
                "claim_count": len(result["claims"]),
                "includes_latest_recording": True,
                "scope": "first data query after process restart; OS cache not purged; no model generation",
            },
        )
        db.close()
        command(
            "durability-after-source",
            "audit_graph.py",
            "--corpus",
            corpus,
            "--env-file",
            env,
            "--output",
            private / "durability-after-source.json",
        )
        source_after = json.loads(
            (private / "durability-after-source.json").read_text()
        )
        if (
            source_after["status"] != "ok"
            or source_after["projection_fingerprint"]
            != source_before["projection_fingerprint"]
        ):
            raise ValueError("Source differs after restart")
        overlays_after = {
            name: audit_overlay(corpus, env, rev)
            for name, rev in [
                ("frozen", config["frozen_load_revision"]),
                ("latest", revision),
            ]
        }
        if overlays_after != overlays_before:
            raise ValueError("Overlay differs after restart")
        private_json(private / "durability-after-overlays.json", overlays_after)
        command(
            "post-restart-boundaries",
            "temporal_replay.py",
            "--corpus",
            corpus,
            "--env-file",
            env,
            "--revision",
            revision,
            "--output",
            private / "post-restart-boundaries.json",
        )
        if json.loads((private / "post-restart-boundaries.json").read_text())[
            "failures"
        ]:
            raise ValueError("Post-restart boundary failure")
        command(
            "post-restart-questions",
            "recall.py",
            "--questions",
            private / "questions-v1.json",
            "--sha256",
            config["question_sha256"],
            "--corpus",
            corpus,
            "--env-file",
            env,
            "--revision",
            revision,
            "--output",
            private / "post-restart-questions.jsonl",
        )
        replay = [
            json.loads(l)
            for l in (private / "post-restart-questions.jsonl").read_text().splitlines()
        ]
        if (
            replay[-1].get("type") != "complete"
            or len([r for r in replay if "case_id" in r]) != 48
            or any(r.get("status") == "error" for r in replay)
        ):
            raise ValueError("Post-restart query replay incomplete")
        command("post-restart-live-contract", "live_contract.py", "--env-file", env)
        command(
            "post-restart-entity-contract",
            "entity_contract.py",
            "--env-file",
            env,
            "--output",
            private / "post-restart-entity-contract.json",
        )
        command(
            "post-restart-original-search",
            "raw_graph_replay.py",
            "--questions",
            private / "unextracted-questions-v1.json",
            "--sha256",
            config["unextracted_question_sha256"],
            "--corpus",
            corpus,
            "--env-file",
            env,
            "--output",
            private / "post-restart-original-search.jsonl",
        )
        stage("durability_checks_passed")
        # All study writers and owned audit subprocesses are now finished.
        connection = sqlite3.connect(corpus)
        checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        connection.close()
        if checkpoint[0]:
            raise ValueError("SQLite checkpoint is busy; do not copy an active cache")
        if any(p.is_symlink() for p in private.rglob("*")):
            raise ValueError("Unexpected private artifact symlink")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copytree(
            private,
            destination,
            ignore=shutil.ignore_patterns(
                "*-shm", "*-wal", "finish-run.stdout.log", "finish-run.stderr.log"
            ),
        )
        for path in destination.rglob("*"):
            path.chmod(0o700 if path.is_dir() else 0o600)
        destination.chmod(0o700)
        (destination / "active-corpus").write_text(
            str(destination / "corpus-v3.sqlite") + "\n"
        )
        (destination / "active-corpus").chmod(0o600)
        final = {
            "status": "ok",
            "completed_at": datetime.now(UTC).isoformat(),
            "study_receipts": receipts,
            "source_fingerprint": source_after["projection_fingerprint"],
            "overlay_fingerprints": {
                k: v["fingerprint"] for k, v in overlays_after.items()
            },
            "runtime_before": before,
            "runtime_after": after,
            "post_restart_first_data_query_ms": first_ms,
            "private_artifacts": str(destination),
            "source_directory_retained": str(private),
            "stages": log,
            "answer_accuracy_established": False,
            "goal_completion_requires_manual_audit": True,
        }
        private_json(private / "durability-finalization.json", final)
        private_json(destination / "durability-finalization.json", final)
        Path("/tmp/kioku-c360-graph-private-path").write_text(str(destination) + "\n")
        Path("/tmp/kioku-c360-graph-private-path").chmod(0o600)
        stage("finalization_complete", private_artifacts=str(destination))
    finally:
        if awake.poll() is None:
            awake.terminate()
            awake.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    run(args)
