"""Opt-in real Mihari -> backend prepare -> Tsukai -> briefing acceptance probe.

Run in the deployed Mihari environment after initializing an isolated watched
repository whose folder name starts with tsukai-e2e-. Push a new principal-branch
commit first, then run:

  python scripts/tsukai_mihari_e2e.py --repo-id UUID --head FULL_SHA

This invokes the actual worker, writes the isolated fixture's normal briefing and
checkpoint, and verifies durable native job/accounting provenance. It does not
mock transport or model generation. A resumed pass verifies the original changed
content against its immutable prepared snapshot, without regenerating current
sections. Re-running at an acknowledged HEAD must use the normal no-model gate.
Fixture provisioning/cleanup belongs to the
caller. Credentials come only from the existing process environment and are never
printed. A successful SQL/unit test is not a substitute for running this probe.
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path


def section(row, name):
    sections = {
        **(row.get("sections") or {}),
        **((row.get("content") or {}).get("sections") or {}),
    }
    return sections.get(name) or {}


def content_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def publication_change(before, after, prepared):
    """A resumed pass proves the original update from its immutable snapshot."""
    snapshot = prepared.get("snapshot") or {}
    if "current" not in snapshot:
        raise RuntimeError(
            "Native publication is missing its original evidence snapshot"
        )
    original = snapshot["current"]
    after_digest = content_digest(after.get("content"))
    if content_digest(original) == after_digest:
        raise RuntimeError(
            "Published native job did not change the target briefing content"
        )
    return {
        "before_digest": content_digest(original),
        "observed_before_digest": content_digest(before.get("content")),
        "after_digest": after_digest,
        "resumed_pass": content_digest(before.get("content")) == after_digest,
    }


def run(repo_id, head, area, worker_path):
    if not re.fullmatch(r"[0-9a-f]{40,64}", head):
        raise ValueError("--head must be a full principal-branch SHA")
    spec = importlib.util.spec_from_file_location(
        "mihari_acceptance_worker", worker_path
    )
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    repos = worker.rest_get(
        "watched_repos", {"id": f"eq.{repo_id}", "select": "*", "limit": "1"}
    )
    if not repos:
        raise RuntimeError("Isolated watched repository not found")
    repo = repos[0]
    if repo["user_id"] != os.environ.get("TSUKAI_CREDENTIAL_OWNER_ID"):
        raise RuntimeError(
            "Fixture must belong to the configured native credential owner"
        )
    folders = worker.rest_get(
        "folders", {"id": f"eq.{repo['folder_id']}", "select": "name", "limit": "1"}
    )
    if not folders or not folders[0]["name"].startswith("tsukai-e2e-"):
        raise RuntimeError("Probe writes are restricted to folders named tsukai-e2e-*")
    filters = {
        "folder_id": f"eq.{repo['folder_id']}",
        "user_id": f"eq.{repo['user_id']}",
    }

    def latest():
        rows = worker.rest_get(
            "folder_summaries",
            {
                **filters,
                "select": "content,sections,generated_at",
                "order": "generated_at.desc",
                "limit": "1",
            },
        )
        if not rows:
            raise RuntimeError(
                "Initialize the fixture briefing before running this probe"
            )
        return rows[0]

    before = section(latest(), area)
    if before.get("provenance") == "user_ui":
        raise RuntimeError("Fixture target section must be auto-maintained")
    keys = worker.rest_get(
        "user_git_keys",
        {
            "user_id": filters["user_id"],
            "select": "private_key_encrypted",
            "limit": "1",
        },
    )
    if not keys:
        raise RuntimeError("Fixture owner has no Mihari git identity")
    worker.process_repo(repo, keys[0])
    watched = worker.rest_get(
        "watched_repos",
        {"id": f"eq.{repo_id}", "select": "last_sha,last_error", "limit": "1"},
    )[0]
    if watched.get("last_sha") != head or watched.get("last_error"):
        raise RuntimeError("Actual Mihari pass did not acknowledge the expected HEAD")
    after = section(latest(), area)
    if after.get("provenance") != "auto" or not (
        after.get("updated_by") or ""
    ).startswith("mihari"):
        raise RuntimeError("Published section is missing Mihari auto provenance")
    freshness = worker.rest_get(
        "repo_freshness", {**filters, "select": "section_reviews", "limit": "1"}
    )[0]
    if (freshness.get("section_reviews", {}).get(area) or {}).get("head_sha") != head:
        raise RuntimeError("Target section has no review marker for the expected HEAD")
    preparations = worker.rest_get(
        "maintenance_preparations",
        {
            **filters,
            "head_sha": f"eq.{head}",
            "operation": f"eq.{area}",
            "select": "id,request,snapshot,execution_job_id,publication",
            "order": "created_at.desc",
        },
    )
    prepared = next(
        (
            p
            for p in preparations
            if p.get("execution_job_id") and p.get("publication", {}).get("updated")
        ),
        None,
    )
    if not prepared:
        raise RuntimeError("No committed direct native maintenance preparation found")
    request = prepared["request"]
    if (
        request.get("caller") != "mihari"
        or request.get("profile") != "completion"
        or request.get("conversation_id")
        or request.get("tool_allowlist")
    ):
        raise RuntimeError("Job was not a fresh, tool-free Mihari native completion")
    job = prepared["execution_job_id"]
    usage = worker.rest_get(
        "tsukai_native_usage",
        {
            "owner_id": filters["user_id"],
            "job_id": f"eq.{job}",
            "select": "attempt_id,outcome,source,model,billing_mode,complete,list_equivalent_usd",
        },
    )
    if not usage or any(
        u["source"] != "mihari" or u["billing_mode"] != "subscription" for u in usage
    ):
        raise RuntimeError("Native per-attempt subscription usage is missing")
    receipt = worker.rest_get(
        "maintenance_usage_outbox", {"job_id": f"eq.{job}", "select": "captured_at"}
    )
    ack = worker.rest_get(
        "maintenance_runner_ack_outbox",
        {"job_id": f"eq.{job}", "select": "acknowledged_at"},
    )
    if (
        not receipt
        or not receipt[0].get("captured_at")
        or not ack
        or not ack[0].get("acknowledged_at")
    ):
        raise RuntimeError(
            "Usage copy or runner acknowledgement is still pending; rerun reconciliation"
        )
    return {
        "ok": True,
        "repo_id": repo_id,
        "folder_id": repo["folder_id"],
        "head_sha": head,
        "section": area,
        **publication_change(before, after, prepared),
        "already_indexed_at_start": repo.get("last_sha") == head,
        "preparation_id": prepared["id"],
        "job_id": job,
        "provenance": after["provenance"],
        "updated_by": after["updated_by"],
        "reviewed_head": head,
        "attempts": usage,
        "usage_captured": True,
        "runner_acknowledged": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument(
        "--section",
        default="activity",
        choices=["activity", "deployment", "how_it_runs"],
    )
    parser.add_argument(
        "--worker-path",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "mihari" / "mihari.py",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.repo_id, args.head, args.section, args.worker_path), indent=2
        )
    )


if __name__ == "__main__":
    main()
