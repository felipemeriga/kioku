"""Batch maintenance and repeated repository-session retention comparisons."""

import json
import argparse
from pathlib import Path

from native import NativeRunner
from soak import fixture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--revisions", type=int, default=12)
    args = parser.parse_args()
    root = Path("/private/tmp/kioku-claude-poc-runtime") / (
        "variants-strict" if args.strict else "variants"
    )
    runner = NativeRunner(root / "calls")
    checks = []
    session = None
    schema = {
        "type": "object",
        "properties": {
            "max_attempts": {"type": "integer"},
            "selected": {"type": "array", "items": {"type": "string"}},
            "activity": {"type": "string"},
            "documentation": {"type": "string"},
            "deployment_verified": {"type": "boolean"},
        },
        "required": [
            "max_attempts",
            "selected",
            "activity",
            "documentation",
            "deployment_verified",
        ],
        "additionalProperties": False,
    }
    if args.strict:
        schema["properties"]["selected"]["items"]["enum"] = [
            "overview",
            "architecture",
            "how_it_runs",
            "deployment",
            "activity",
            "documentation",
        ]
    for revision in range(args.revisions):
        repo, attempts = fixture(root, "batch-worker", revision)
        sources = "\n\n".join(
            f"--- {p.relative_to(repo)} ---\n{p.read_text()}"
            for p in [
                repo / "README.md",
                repo / "src/worker.py",
                repo / ".github/workflows/deploy.yml",
            ]
        )
        prompt = (
            "Maintain existing repository briefing areas in ONE response. The only changed fact "
            "is retry attempts in worker.py. Current source below supersedes earlier versions. "
            "Select only factual areas affected. Return current max_attempts, selected areas, "
            "activity (one sentence), documentation (two sentences) and deployment_verified=false "
            "unless supplied evidence establishes actual deployment. Do not invent facts.\n"
            + sources
        )
        if args.strict:
            prompt = (
                "Valid briefing area names are overview, architecture, how_it_runs, deployment, activity, documentation.\n"
                + prompt
            )
        for mode in ["stateless", "stateful"]:
            record = runner.call(
                f"batch-{mode}-revision-{revision}",
                prompt,
                resume=session if mode == "stateful" else None,
                persist=mode == "stateful",
                schema=schema,
                exclude_instructions=True,
                system_prompt="You maintain repository facts using only supplied source. Be concise.",
            )
            if mode == "stateful":
                session = record.get("session_id") or session
            output = record.get("structured_output") or {}
            checks.append(
                {
                    "revision": revision,
                    "mode": mode,
                    "call_id": record["id"],
                    "expected_attempts": attempts,
                    "actual_attempts": output.get("max_attempts"),
                    "correct": output.get("max_attempts") == attempts
                    and output.get("deployment_verified") is False,
                    "elapsed_s": record["elapsed_s"],
                    "list_cost_usd": record["list_cost_usd"],
                    "usage": record["usage"],
                    "selected": output.get("selected"),
                }
            )
            (root / "checks.json").write_text(json.dumps(checks, indent=2))
            print(
                json.dumps({k: v for k, v in checks[-1].items() if k != "usage"}),
                flush=True,
            )


if __name__ == "__main__":
    main()
