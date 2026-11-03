"""Exercise the actual backend review-plan prompt through native CLI transport."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from native import NativeRunner
from soak import HERE


def main():
    sys.path.insert(0, str(HERE.parents[1] / "backend"))
    from routes import mihari
    import mcp_server

    root = Path("/private/tmp/kioku-claude-poc-runtime/prompt-parity")
    runner = NativeRunner(root / "calls")
    sections = {
        "overview": "Invoice worker receives and retries invoice delivery jobs.",
        "architecture": "One Python worker uses PostgreSQL for jobs and Redis for leases; no separate API service.",
        "how_it_runs": "Run python -m src.worker; PostgreSQL and Redis are required.",
        "deployment": "GitHub workflow runs tests and publishes an image on push to main.",
        "activity": "Recent invoice worker reliability changes.",
        "documentation": "The worker retries transient429/503responses at most3times;401/403fail permanently.",
    }
    snapshot = {
        "content": {
            "sections": {name: {"content": value} for name, value in sections.items()}
        }
    }
    scenarios = [
        (
            "retry-policy",
            ["src/worker.py"],
            "Increase transient retries from3to7",
            "-MAX_ATTEMPTS = 3\n+MAX_ATTEMPTS = 7",
            {"activity", "documentation"},
        ),
        (
            "run-command",
            ["README.md"],
            "Rename worker startup entrypoint",
            "-Run python -m src.worker\n+Run python -m src.invoice_worker",
            {"activity", "how_it_runs", "documentation"},
        ),
        (
            "deploy-trigger",
            [".github/workflows/deploy.yml"],
            "Publish releases only on version tags",
            "-branches: [main]\n+tags: ['v*']",
            {"activity", "deployment", "documentation"},
        ),
        (
            "new-api-service",
            ["src/api.py", "docker-compose.yml"],
            "Add HTTP API service for job submission",
            "+api:\n+  command: uvicorn src.api:app\n+@app.post('/jobs')\n+def submit_job(): return queue.enqueue()",
            {"activity", "architecture", "overview", "how_it_runs", "documentation"},
        ),
        (
            "format-only",
            ["src/worker.py"],
            "Format code without behavior change",
            "-return status in (429,503)\n+return status in (429, 503)",
            {"activity"},
        ),
        (
            "tests-only",
            ["tests/test_retry.py"],
            "Add retry boundary tests without runtime changes",
            "+def test_unauthorized_is_not_retried():\n+    assert retryable(401) is False",
            {"activity"},
        ),
    ]
    schema = {
        "type": "object",
        "properties": {
            "selected": {
                "type": "array",
                "items": {"type": "string", "enum": list(sections)},
            }
        },
        "required": ["selected"],
        "additionalProperties": False,
    }
    outcomes = []
    for model in ["haiku", "sonnet"]:
        for label, paths, subject, diff, expected in scenarios:
            db = MagicMock()
            db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
                {"abstract": sections["documentation"]}
            ]
            records = []

            def native_complete(**kwargs):
                record = runner.call(
                    f"actual-review-plan-{model}-{label}",
                    json.dumps(kwargs["messages"]),
                    model=model,
                    schema=schema,
                    persist=False,
                    exclude_instructions=True,
                    system_prompt=kwargs["system"],
                )
                records.append(record)
                if record["returncode"]:
                    raise RuntimeError(record["subtype"])
                return SimpleNamespace(
                    content=[
                        SimpleNamespace(text=json.dumps(record["structured_output"]))
                    ]
                )

            with (
                patch.object(
                    mihari,
                    "_api_key_auth",
                    return_value=("fixture-user", "fixture-folder", "synthetic"),
                ),
                patch.object(mihari, "get_supabase", return_value=db),
                patch.object(
                    mcp_server,
                    "_descendant_folder_ids",
                    return_value=["fixture-folder"],
                ),
                patch(
                    "services.folder_summary.repo.get_latest_summary",
                    return_value=snapshot,
                ),
                patch("services.llm.complete", side_effect=native_complete),
            ):
                result = mihari.review_plan(
                    mihari.ReviewPlanRequest(
                        folder_id="fixture-folder",
                        head_sha="a" * 40,
                        changed_paths=paths,
                        commits=[subject],
                        patch=diff,
                    ),
                    MagicMock(),
                )
            selected = set(result["selected"])
            outcomes.append(
                {
                    "label": label,
                    "model": model,
                    "selected": sorted(selected),
                    "expected_minimal": sorted(expected),
                    "extra_areas": sorted(selected - expected),
                    "missing_areas": sorted(expected - selected),
                    "call_id": records[0]["id"],
                    "elapsed_s": records[0]["elapsed_s"],
                }
            )
            (root / "checks.json").write_text(json.dumps(outcomes, indent=2))
            print(json.dumps(outcomes[-1]), flush=True)


if __name__ == "__main__":
    main()
