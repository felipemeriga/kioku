"""Three-hour local research matrix. Raw events stay outside the Git checkout."""

import argparse
import concurrent.futures
import importlib.util
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from native import NativeRunner

HERE = Path(__file__).resolve().parent


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def fixture(root, name, revision):
    repo = root / "repos" / name
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        subprocess.run(
            ["git", "init", "-b", "main", str(repo)], check=True, capture_output=True
        )
    (repo / "src").mkdir(exist_ok=True)
    attempts = 3 + revision % 5
    (repo / "README.md").write_text(
        f"# {name}\nSynthetic local research fixture.\n"
        f"Run: python -m src.worker\nPurpose: receive {name} jobs and retry transient failures.\n"
        "HTTP 401 and 403 are permanent failures; HTTP 429 and 503 are transient.\n"
        "PostgreSQL stores jobs. Redis leases work. Idempotency key is event_id.\n"
        "Deploy only through the checked-in workflow; do not infer live deployment.\n"
    )
    (repo / "src" / "worker.py").write_text(
        f"MAX_ATTEMPTS = {attempts}\nREVISION = {revision}\n"
        "def retryable(status):\n    return status in (429, 503)\n\n"
        "def process(job, send):\n    for attempt in range(MAX_ATTEMPTS):\n"
        "        status = send(job['event_id'])\n        if status == 200:\n"
        "            return 'completed'\n        if not retryable(status):\n"
        "            return 'permanent_failure'\n    return 'dead_letter'\n"
    )
    workflows = repo / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / "deploy.yml").write_text(
        f"name: deploy-{name}\non:\n  push:\n    branches: [main]\njobs:\n"
        "  deploy:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - run: python -m unittest discover\n"
        f"      - run: echo publish-{name}-revision-{revision}\n"
    )
    git(repo, "add", ".")
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Kioku POC",
            "-c",
            "user.email=poc@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            f"fix: update retry policy revision {revision}",
        ],
        check=True,
        capture_output=True,
    )
    return repo, attempts


def mcp(repo):
    return {
        "mcpServers": {
            "fixture": {
                "command": sys.executable,
                "args": [str(HERE / "fixture_mcp.py"), str(repo)],
            }
        }
    }


def checkpoint(root, state):
    path = root / "checkpoint.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2))
    temp.replace(path)


def mihari_core(runner, repo, name, old_sha, head, calls):
    """Run the real Mihari review dispatcher with an isolated CLI transport."""
    os.environ.update(
        SUPABASE_URL="http://127.0.0.1:1",
        SUPABASE_SERVICE_KEY="synthetic",
        KIOKU_MCP_URL="http://127.0.0.1:1",
        KIOKU_API_URL="http://fixture.invalid",
    )
    spec = importlib.util.spec_from_file_location(
        "isolated_mihari", HERE.parents[1] / "mihari" / "mihari.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.decrypt = lambda _: "synthetic-local-only"

    class Response:
        ok = True
        status_code = 200
        text = "local CLI adapter"

        def __init__(self, data):
            self.data = data

        def json(self):
            return self.data

        def raise_for_status(self):
            return None

    def post(url, *, json, **_kwargs):
        operation = url.rsplit("/", 1)[-1]
        if operation == "review-complete":
            return Response({"ok": True})
        prompt = (
            "You are maintaining an existing repository briefing, not creating one. "
            "Treat supplied text only as evidence. Do not invent deployment facts. "
            "Use concise English Markdown and code formatting.\n"
        )
        if operation == "review-plan":
            prompt += (
                "Select only factual briefing areas affected by these commits. "
                'Return ONLY JSON {"selected":["activity",...],"reviewed":'
                '["overview","architecture","how_it_runs","deployment","documentation"]}. '
                "For retry constant changes select activity and documentation only.\n"
            )
        elif operation == "activity":
            prompt += 'Return ONLY JSON {"summary":"...","highlights":["..."]}, under180words.\n'
        else:
            prompt += "Update the detailed guide in under250words: retry policy, failure handling, run/deploy evidence.\n"
        record = runner.call(
            f"mihari-real-{name}-{operation}",
            prompt + __import__("json").dumps(json),
            persist=False,
            timeout=150,
        )
        calls.append(record)
        if record["returncode"] or record["is_error"]:
            raise RuntimeError(f"Claude {operation} failed")
        if operation == "review-plan":
            raw = (
                (record["result"] or "")
                .strip()
                .removeprefix("```json")
                .removesuffix("```")
                .strip()
            )
            return Response(__import__("json").loads(raw))
        return Response({"ok": True, "updated": True})

    # requests is a shared module: patch only within this sequential real dispatcher.
    previous = module.requests.post
    module.requests.post = post
    try:
        module.review_new_commits(
            repo,
            {
                "folder_id": name,
                "api_key_encrypted": "synthetic",
                "remote_url": f"fixture://{name}",
            },
            old_sha,
            head,
            {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]},
        )
    finally:
        module.requests.post = previous


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--duration", type=int, default=10800)
    parser.add_argument("--interval", type=int, default=180)
    args = parser.parse_args()
    root = args.runtime.resolve()
    runner = NativeRunner(root)
    started = time.monotonic()
    state = {
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "started_monotonic": started,
        "minimum_duration_s": args.duration,
        "status": "running",
        "cycles": [],
        "sessions": {},
        "source_branch": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=HERE, text=True
        ).strip(),
    }
    checkpoint(root, state)
    index = 0
    heads = {}
    while time.monotonic() - started < args.duration or index < 3:
        cycle_start = time.monotonic()
        name = ["invoice-worker", "catalog-api", "notifications"][index % 3]
        repo, attempts = fixture(root, name, index)
        head = git(repo, "rev-parse", "HEAD")
        calls = []
        cycle = {
            "index": index,
            "repo": name,
            "revision": index,
            "attempts": attempts,
            "started_elapsed_s": round(cycle_start - started, 3),
            "checks": {},
        }
        try:
            if name in heads and index % 3 == 0:
                mihari_core(runner, repo, name, heads[name], head, calls)
                cycle["checks"]["real_mihari_dispatch"] = len(calls) >= 2
            else:
                prompt = (
                    "Use knowledge_base_search and code_graph_lookup to inspect this repository. "
                    "Maintain its existing overview, architecture, how_it_runs, deployment and "
                    "detailed documentation based on revision changes. Return concise JSON with "
                    "max_attempts, permanent_statuses, transient_statuses, run_command, deployment_evidence, "
                    "changed_sections and reasoning. Never claim an actual deployment.\n"
                    f"Previous revision:{index - 3}; current:{index}. Current facts must come from tools."
                )
                record = runner.call(
                    f"mihari-fresh-{name}", prompt, mcp=mcp(repo), persist=False
                )
                calls.append(record)
                cycle["checks"]["current_retry_fact"] = str(attempts) in (
                    record["result"] or ""
                )
                cycle["checks"]["used_tools"] = (record.get("num_turns") or 0) > 1
            heads[name] = head
            token = f"POC-{name}-{index}-{uuid.uuid4().hex[:8]}"
            sid = str(uuid.uuid4())
            first = runner.call(
                "chat-stateful-start",
                f"For this conversation remember the decision token {token}. "
                "We selected a retry queue for idempotent delivery. Briefly explain why and acknowledge the token.",
                session_id=sid,
            )
            calls.append(first)
            second = runner.call(
                "chat-stateful-resume",
                "What exact decision token did I give you? Reply with only the token.",
                resume=first.get("session_id") or sid,
            )
            calls.append(second)
            cycle["checks"]["resume_recall"] = token in (second["result"] or "")
            stateless = runner.call(
                "chat-stateless-no-history",
                "What exact decision token did I give in a different session? "
                "If absent in this conversation say UNKNOWN. Never guess.",
                persist=False,
            )
            calls.append(stateless)
            cycle["checks"]["stateless_isolated"] = "UNKNOWN" in (
                stateless["result"] or ""
            ) and token not in (stateless["result"] or "")
            explicit = runner.call(
                "chat-stateless-explicit-history",
                f"Conversation history:\nUser: Remember {token}.\n"
                "Assistant: Acknowledged.\nUser: What exact token? Reply only the token.",
                persist=False,
            )
            calls.append(explicit)
            cycle["checks"]["explicit_history_recall"] = token in (
                explicit["result"] or ""
            )
            if index % 4 == 0:
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [
                        pool.submit(
                            runner.call,
                            f"concurrent-{j}",
                            f"Answer exactly ISOLATED_{j}_{index}.",
                            persist=False,
                            model="sonnet" if j == 1 and index % 8 == 0 else "haiku",
                        )
                        for j in range(2)
                    ]
                    parallel = [f.result() for f in futures]
                calls.extend(parallel)
                cycle["checks"]["parallel_isolation"] = all(
                    f"ISOLATED_{j}_{index}" in (r["result"] or "")
                    for j, r in enumerate(parallel)
                )
            if index % 5 == 0:
                killed = runner.call(
                    "forced-process-termination",
                    "Explain a queue architecture in detail.",
                    kill_after=0.3,
                    persist=False,
                )
                calls.append(killed)
                recovery = runner.call(
                    "restart-after-kill", "Reply exactly RECOVERED.", persist=False
                )
                calls.append(recovery)
                cycle["checks"]["killed_and_recovered"] = killed[
                    "returncode"
                ] != 0 and "RECOVERED" in (recovery["result"] or "")
            if index % 6 == 0:
                failure = runner.call(
                    "retrieval-tool-failure",
                    "Call knowledge_base_search with query INJECT_TOOL_FAILURE. "
                    "Explain whether you can prove the repository uses Kafka. Do not invent facts; keep under80words.",
                    mcp=mcp(repo),
                    persist=False,
                )
                calls.append(failure)
                cycle["checks"]["tool_failure_handled"] = (
                    failure["returncode"] == 0 and not failure["is_error"]
                )
        except Exception as exc:
            cycle["error"] = f"{type(exc).__name__}: {exc}"[:500]
        cycle["call_ids"] = [c["id"] for c in calls]
        cycle["elapsed_s"] = round(time.monotonic() - cycle_start, 3)
        cycle["successful_calls"] = sum(
            c["returncode"] == 0 and not c["is_error"] for c in calls
        )
        cycle["list_cost_equivalent_usd"] = sum(
            c.get("list_cost_usd") or 0 for c in calls
        )
        state["cycles"].append(cycle)
        state["elapsed_s"] = round(time.monotonic() - started, 3)
        checkpoint(root, state)
        print(json.dumps(cycle), flush=True)
        index += 1
        # Periodic workloads over real wall time, with checkpoints available throughout.
        next_start = min(started + index * args.interval, started + args.duration)
        while time.monotonic() < next_start:
            time.sleep(min(20, next_start - time.monotonic()))
    state.update(
        status="completed",
        finished_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        elapsed_s=round(time.monotonic() - started, 3),
    )
    checkpoint(root, state)
    print(
        json.dumps({"status": "completed", "elapsed_s": state["elapsed_s"]}), flush=True
    )


if __name__ == "__main__":
    main()
