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


def documentation_change(before, after, prepared, mcp_before, mcp_after):
    """Prove a full document changed, rather than its unrelated briefing abstract."""
    original = (prepared.get("snapshot") or {}).get("current")
    if (
        not isinstance(original, dict)
        or not original.get("id")
        or not original.get("content")
    ):
        raise RuntimeError("Detailed documentation has no original revision snapshot")
    if before.get("content") != mcp_before or after.get("content") != mcp_after:
        raise RuntimeError(
            "Scoped MCP detailed documentation differs from the persisted full body"
        )
    if not after.get("id") or after["id"] == original["id"]:
        raise RuntimeError("Detailed documentation has no newly published revision")
    evidence = publication_change(
        before, after, {"snapshot": {"current": original["content"]}}
    )
    return {
        **evidence,
        "original_document_revision": original["id"],
        "document_revision": after["id"],
        "document_chars": len(after["content"]),
        "scoped_mcp_full_body_verified": True,
    }


def read_mcp_documentation(worker, url, key, folder_id):
    """Actual scoped MCP wire call; no model generation or bearer logging."""
    if not url:
        raise ValueError("Documentation acceptance requires an explicit --mcp-url")
    with worker.requests.Session() as client:
        client.headers.update(
            {
                "Authorization": "Bearer " + key,
                "Accept": "application/json, text/event-stream",
            }
        )

        def rpc(body):
            response = client.post(url, json=body, timeout=30)
            response.raise_for_status()
            session = response.headers.get("mcp-session-id")
            if session:
                client.headers["Mcp-Session-Id"] = session
            if "text/event-stream" not in response.headers.get("content-type", ""):
                return response.json()
            # SSE is UTF-8 even without a charset parameter. requests otherwise
            # defaults text/* to Latin-1 and corrupts non-ASCII Markdown evidence.
            for block in (
                response.content.decode("utf-8").replace("\r\n", "\n").split("\n\n")
            ):
                data = "\n".join(
                    line[5:].lstrip()
                    for line in block.splitlines()
                    if line.startswith("data:")
                )
                if data:
                    value = json.loads(data)
                    if value.get("id") == body.get("id"):
                        return value
            raise RuntimeError("MCP response has no matching RPC result")

        initialized = rpc(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "tsukai-documentation-acceptance",
                        "version": "1",
                    },
                },
            }
        )
        if initialized.get("error"):
            raise RuntimeError("MCP initialization failed")
        client.headers["MCP-Protocol-Version"] = initialized["result"][
            "protocolVersion"
        ]
        notification = client.post(
            url,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            timeout=30,
        )
        notification.raise_for_status()
        try:
            response = rpc(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "get_repo_documentation",
                        "arguments": {"folder": folder_id},
                    },
                }
            )
            result = response.get("result") or {}
            if response.get("error") or result.get("isError"):
                raise RuntimeError("Scoped MCP detailed documentation lookup failed")
            body = "\n".join(
                item["text"]
                for item in result.get("content", [])
                if item.get("type") == "text"
            )
            if not body.strip() or body.startswith(("Error", "No documentation saved")):
                raise RuntimeError("Scoped MCP detailed documentation is unavailable")
            return body
        finally:
            if client.headers.get("Mcp-Session-Id"):
                client.delete(url, timeout=10)


def run(repo_id, head, area, worker_path, mcp_url=None):
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

    def latest_document():
        rows = worker.rest_get(
            "repo_documentation",
            {
                **filters,
                "select": "id,content,abstract,generated_at",
                "order": "generated_at.desc",
                "limit": "1",
            },
        )
        if not rows:
            raise RuntimeError(
                "Initialize detailed documentation with an agent before this probe"
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
    document_before = latest_document() if area == "documentation" else None
    mcp_before = (
        read_mcp_documentation(
            worker,
            mcp_url,
            worker.decrypt(repo["api_key_encrypted"]),
            repo["folder_id"],
        )
        if area == "documentation"
        else None
    )
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
    change = (
        documentation_change(
            document_before,
            latest_document(),
            prepared,
            mcp_before,
            read_mcp_documentation(
                worker,
                mcp_url,
                worker.decrypt(repo["api_key_encrypted"]),
                repo["folder_id"],
            ),
        )
        if area == "documentation"
        else publication_change(before, after, prepared)
    )
    return {
        "ok": True,
        "repo_id": repo_id,
        "folder_id": repo["folder_id"],
        "head_sha": head,
        "section": area,
        **change,
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
        choices=["activity", "deployment", "how_it_runs", "documentation"],
    )
    parser.add_argument("--mcp-url", default=os.getenv("TSUKAI_E2E_MCP_URL"))
    parser.add_argument(
        "--worker-path",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "mihari" / "mihari.py",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.repo_id, args.head, args.section, args.worker_path, args.mcp_url),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
