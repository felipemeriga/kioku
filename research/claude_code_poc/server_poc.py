"""Isolated server fixture POC, with an optional container-to-host Unix broker."""

import argparse
import concurrent.futures
import json
import os
import socketserver
import sys
import threading
import time
from pathlib import Path

from native import NativeRunner


def setup(root):
    source = root / "source"
    source.mkdir(parents=True, exist_ok=True)
    (source / "worker.py").write_text(
        "MAX_ATTEMPTS = 7\ndef deliver(event_id):\n    return event_id\n"
    )
    (source / "README.md").write_text(
        "Run: python worker.py. Deployment is not established. Idempotency uses event_id.\n"
    )
    return source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--broker", action="store_true")
    args = parser.parse_args()
    root = args.runtime.resolve()
    source = setup(root)
    runner = NativeRunner(root / "calls")
    mcp = {
        "mcpServers": {
            "fixture": {
                "command": sys.executable,
                "args": [str(Path(__file__).with_name("fixture_mcp.py")), str(source)],
            }
        }
    }
    system = (
        "You are Kioku, a grounded assistant. Explicit prior messages supplied by the "
        "caller are authoritative conversation context: answer recalled user choices "
        "from those messages without requiring repository verification. Distinguish "
        "those decisions from implementation claims, which require retrieved source. "
        "Preserve exact facts and never invent deployment evidence."
    )
    if args.broker:
        socket_path = root / "broker.sock"
        socket_path.unlink(missing_ok=True)
        limiter = threading.BoundedSemaphore(2)
        session_locks = {}
        session_guard = threading.Lock()

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                request = json.loads(self.rfile.readline(200000))
                if request.get("action") == "health":
                    self.wfile.write(b'{"healthy":true}\n')
                    return
                with session_guard:
                    lock = session_locks.setdefault(
                        request.get("resume") or id(request), threading.Lock()
                    )
                if not lock.acquire(blocking=False):
                    self.wfile.write(b'{"error":"session_busy"}\n')
                    return
                try:
                    with limiter:

                        def emit(event):
                            if event.get("type") in ("stream_event", "result"):
                                try:
                                    self.wfile.write(
                                        (json.dumps(event) + "\n").encode()
                                    )
                                    self.wfile.flush()
                                except BrokenPipeError:
                                    pass

                        row = runner.call(
                            "container-broker",
                            request["prompt"],
                            resume=request.get("resume"),
                            mcp=mcp if request.get("maintenance") else None,
                            system_prompt=system,
                            on_event=emit,
                            thinking_tokens=0,
                        )
                        try:
                            self.wfile.write(
                                (
                                    json.dumps(
                                        {
                                            "broker_result": row["result"],
                                            "returncode": row["returncode"],
                                            "session_id": row["session_id"],
                                            "elapsed_s": row["elapsed_s"],
                                        }
                                    )
                                    + "\n"
                                ).encode()
                            )
                        except BrokenPipeError:
                            pass

                finally:
                    lock.release()

        with socketserver.ThreadingUnixStreamServer(
            str(socket_path), Handler
        ) as server:
            os.chmod(socket_path, 0o600)
            print(json.dumps({"broker_ready": str(socket_path)}), flush=True)
            server.serve_forever()
        return
    checks = []
    started = time.monotonic()

    def note(name, passed, rows):
        checks.append(
            {"name": name, "passed": passed, "call_ids": [r["id"] for r in rows]}
        )
        (root / "checks.json").write_text(json.dumps(checks, indent=2))
        print(json.dumps(checks[-1]), flush=True)

    initial = runner.call(
        "server-chat",
        "We selected PostgreSQL outbox for event delivery and event_id as idempotency key. Acknowledge.",
        system_prompt=system,
    )
    resumed = runner.call(
        "server-resume",
        "What database pattern and idempotency key did we select?",
        resume=initial["session_id"],
        system_prompt=system,
    )
    note(
        "stateful-chat",
        "PostgreSQL" in resumed["result"] and "event_id" in resumed["result"],
        [initial, resumed],
    )
    stateless = runner.call(
        "server-stateless",
        "Prior messages: User selected PostgreSQL outbox and event_id. Question: What pattern and idempotency key were adopted?",
        persist=False,
        system_prompt=system,
    )
    note(
        "stateless-chat",
        "PostgreSQL" in stateless["result"] and "event_id" in stateless["result"],
        [stateless],
    )
    maintenance = runner.call(
        "server-maintenance",
        "Inspect the source using both knowledge_base_search and code_graph_lookup. What is MAX_ATTEMPTS, run command, idempotency key, and deployment evidence?",
        mcp=mcp,
        persist=False,
        system_prompt=system,
    )
    note(
        "mcp-maintenance",
        "7" in maintenance["result"]
        and "event_id" in maintenance["result"]
        and maintenance["num_turns"] > 1,
        [maintenance],
    )
    (source / "worker.py").write_text(
        "MAX_ATTEMPTS = 9\ndef deliver(event_id):\n    return event_id\n"
    )
    changed = runner.call(
        "server-fresh-maintenance",
        "Read current worker.py using knowledge_base_search. What is MAX_ATTEMPTS now? Answer one sentence.",
        mcp=mcp,
        persist=False,
        system_prompt=system,
    )
    note("changed-source", "9" in changed["result"], [changed])
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(
            pool.map(
                lambda index: runner.call(
                    f"server-parallel-{index}",
                    f"Answer exactly SERVER_{index}.",
                    persist=False,
                    system_prompt=system,
                ),
                range(2),
            )
        )
    note(
        "parallel-isolation",
        all(f"SERVER_{i}" in row["result"] for i, row in enumerate(rows)),
        rows,
    )
    killed = runner.call(
        "server-cancel",
        "Explain transactional outbox architecture in detail.",
        persist=False,
        kill_after=0.3,
    )
    recovered = runner.call(
        "server-after-cancel", "Answer RECOVERED.", persist=False, system_prompt=system
    )
    note(
        "cancel-and-recover",
        killed["returncode"] != 0 and "RECOVERED" in recovered["result"],
        [killed, recovered],
    )
    (root / "summary.json").write_text(
        json.dumps(
            {"elapsed_s": time.monotonic() - started, "checks": checks}, indent=2
        )
    )


if __name__ == "__main__":
    main()
