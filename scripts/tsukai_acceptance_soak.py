"""Durable supervisor for real integrated acceptance probes.

This does not provide probes or assert full E2E coverage. Supply a private JSON
plan with commands that exercise the deployed app and independently assert their
results. Commands inherit credentials from the environment; put no credentials
in command arguments. Probe stdout/stderr are discarded: each probe must write
its own sanitized evidence. Every interval is credited only after all scheduled
checks pass; failed/blocked intervals do not advance the healthy soak clock.

Plan: {"ready": true, "build": "SHA", "target": "https://...",
       "cases": [{"name": "chat", "argv": ["python", "probe.py"],
                  "every": 240, "timeout": 180}]}

The readiness declaration must come from the integrating operator. Never set it
while waiting for builds or using fixtures as substitutes for actual services.
Use a new output directory after changing the deployed build or probe plan.
"""

import argparse
import datetime
import json
import os
import re
import subprocess
import time
from pathlib import Path


def append(path, record):
    with path.open("a") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def supervise(plan, output, required_seconds):
    if not plan.get("ready") or not plan.get("build") or not plan.get("target"):
        raise ValueError("Integrated operator readiness/build/target required")
    cases = plan["cases"]
    if not cases or len({c["name"] for c in cases}) != len(cases):
        raise ValueError("At least one uniquely named real probe is required")
    for case in cases:
        if not re.fullmatch(r"[a-z0-9_-]+", case["name"]):
            raise ValueError("Probe names must contain only lowercase safe labels")
        if not 30 <= case["every"] <= 300 or not 1 <= case["timeout"] <= 300:
            raise ValueError("Probe cadence must be 30-300s; timeout 1-300s")
        if not case["argv"] or not all(isinstance(x, str) for x in case["argv"]):
            raise ValueError("Probe argv must be a nonempty list of strings")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    events = output / "events.jsonl"
    started = time.monotonic()
    last_tick = started
    healthy_seconds = 0.0
    due = dict.fromkeys((c["name"] for c in cases), started)
    healthy = dict.fromkeys(due, False)
    counts = {name: {"passed": 0, "failed": 0} for name in due}
    append(
        events,
        {
            "event": "started",
            "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "build": plan["build"],
            "target": plan["target"],
            "required_seconds": required_seconds,
        },
    )
    while True:
        now = time.monotonic()
        if all(healthy.values()):
            healthy_seconds += now - last_tick
        last_tick = now
        for case in cases:
            name = case["name"]
            if now < due[name]:
                continue
            began = time.monotonic()
            try:
                result = subprocess.run(
                    case["argv"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=case["timeout"],
                    check=False,
                )
                code = result.returncode
            except subprocess.TimeoutExpired:
                code = 124
            except OSError:
                code = 127
            ended = time.monotonic()
            healthy[name] = code == 0
            counts[name]["passed" if code == 0 else "failed"] += 1
            # Successful probe execution is active integrated testing. Failed
            # or blocked execution earns no credit, including timeout waits.
            if code == 0 and all(healthy.values()):
                healthy_seconds += ended - began
            last_tick = ended
            due[name] = ended + case["every"]
            append(
                events,
                {
                    "event": "probe",
                    "name": name,
                    "exit_code": code,
                    "elapsed_seconds": ended - began,
                    "wall_seconds": ended - started,
                    "healthy_seconds": healthy_seconds,
                },
            )
        checkpoint = {
            "wall_seconds": time.monotonic() - started,
            "healthy_seconds": healthy_seconds,
            "counts": counts,
            "healthy": healthy,
            "duration_met": healthy_seconds >= required_seconds,
            "coverage_claim": "External probe evidence requires operator review",
        }
        temporary = output / "checkpoint.tmp"
        with temporary.open("w") as stream:
            json.dump(checkpoint, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output / "checkpoint.json")
        if checkpoint["duration_met"] and all(healthy.values()):
            append(events, {"event": "duration_met", **checkpoint})
            return checkpoint
        time.sleep(min(10, max(0.1, min(due.values()) - time.monotonic())))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seconds", type=float, default=14460)
    args = parser.parse_args()
    if args.seconds < 14460:
        parser.error("Acceptance soak requires at least 14460 healthy seconds")
    print(
        json.dumps(
            supervise(json.loads(args.plan.read_text()), args.output, args.seconds)
        )
    )


if __name__ == "__main__":
    main()
