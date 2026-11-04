"""Isolated routing experiment: stdlib HTTP, native CLI and API subprocess bridge."""

import argparse
import hashlib
import hmac
import http.client
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from native import NativeRunner

MODEL = "claude-haiku-4-5-20251001"
SYSTEM = "You are Kioku. Answer only from supplied evidence and prior messages. Be concise, accurate, and do not invent deployment. Return only the requested answer, without questions when evidence is sufficient."
PROMPTS = {
    "chat": "Evidence: the invoice worker uses PostgreSQL outbox, event_id for idempotency, MAX_ATTEMPTS=7, and retries429/503. In two concise sentences explain retry and duplicate protection.",
    "mihari": 'Current briefing says retries=3. Source now MAX_ATTEMPTS=7, event_id deduplication, transient429/503retry and401/403permanent failure. No deployment evidence supplied. Return JSON only: {"outcome":"completed","max_attempts":7,"deployment":"unknown"}.',
    "mcp": "Knowledge base evidence: worker.py:42 MAX_ATTEMPTS=7; README: PostgreSQL outbox with event_id idempotency. Answer: which retry limit and idempotency key are recorded? One sentence.",
}
ROOT = None
KEY = None
API = None
NATIVE = None


def emit(writer, event):
    writer.write(("data: " + json.dumps(event) + "\n\n").encode())
    writer.flush()


def capability(role, user="fixture-owner"):
    body = {"role": role, "user": user, "expires": int(time.time()) + 300}
    body["signature"] = hmac.new(
        KEY, json.dumps(body, sort_keys=True).encode(), hashlib.sha256
    ).hexdigest()
    return body


def valid(cap, role):
    body = {k: v for k, v in cap.items() if k != "signature"}
    return (
        cap.get("role") == role
        and cap.get("user") == "fixture-owner"
        and cap.get("expires", 0) > time.time()
        and hmac.compare_digest(
            cap.get("signature", ""),
            hmac.new(
                KEY, json.dumps(body, sort_keys=True).encode(), hashlib.sha256
            ).hexdigest(),
        )
    )


class APIBridge:
    def __init__(self):
        self.lock = threading.Lock()
        self.process = subprocess.Popen(
            [
                "docker",
                "exec",
                "-i",
                "kioku-backend",
                "/app/.venv/bin/python",
                "-u",
                "/tmp/tsukai-routing-api-worker.py",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )

    def call(self, req, callback):
        with self.lock:
            self.process.stdin.write(json.dumps(req) + "\n")
            self.process.stdin.flush()
            for line in self.process.stdout:
                event = json.loads(line)
                callback(event)
                if event.get("type") == "result":
                    return event
        raise RuntimeError("API bridge ended")


def run(req, callback):
    started = time.monotonic()
    first = None

    def output(event):
        nonlocal first
        if event.get("type") == "text" and first is None:
            first = time.monotonic() - started
        callback(event)

    if req["engine"] == "mock":
        output({"type": "text", "text": "fixture"})
        result = {"type": "result", "text": "fixture", "success": True, "model": "mock"}
        output(result)
    elif req["engine"] == "api":
        result = API.call(
            {
                "model": MODEL,
                "system": SYSTEM,
                "prompt": req["prompt"],
                "agent": req.get("agent", False),
            },
            output,
        )
    else:

        def native_event(event):
            if event.get("type") == "assistant":
                for block in event.get("message", {}).get("content", []):
                    if block.get("type") == "tool_use":
                        output(
                            {
                                "type": "tool",
                                "name": block["name"],
                                "input": block.get("input"),
                            }
                        )
            if event.get("type") == "stream_event":
                delta = event.get("event", {}).get("delta", {})
                if delta.get("type") == "text_delta":
                    output({"type": "text", "text": delta["text"]})

        mcp = (
            {
                "mcpServers": {
                    "fixture": {
                        "command": sys.executable,
                        "args": [
                            str(Path(__file__).with_name("fixture_mcp.py")),
                            str(ROOT / "source"),
                        ],
                    }
                }
            }
            if req.get("agent")
            else None
        )
        row = NATIVE.call(
            req["path"],
            req["prompt"],
            model=MODEL,
            thinking_tokens=0,
            persist=bool(req.get("resume") or req.get("stateful")),
            resume=req.get("resume"),
            system_prompt=SYSTEM,
            on_event=native_event,
            exclude_instructions=True,
            mcp=mcp,
            schema=req.get("schema"),
        )
        result = {
            "type": "result",
            "text": row.get("result"),
            "success": row["returncode"] == 0 and not row["is_error"],
            "model": row.get("served_model"),
            "usage": row.get("usage"),
            "session_id": row.get("session_id"),
            "num_turns": row.get("num_turns"),
            "list_equivalent_usd": row.get("list_cost_usd"),
            "structured_output": row.get("structured_output"),
        }
        output(result)
    return {
        "first_text_s": first,
        "total_s": time.monotonic() - started,
        "result": result,
    }


def request_stream(port, body, role="backend"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=180)
    conn.request(
        "POST",
        "/invoke",
        json.dumps(body),
        {"Content-Type": "application/json", "Authorization": "Bearer " + role},
    )
    response = conn.getresponse()
    if response.status != 200:
        raise RuntimeError(f"HTTP {response.status}")
    try:
        for line in response:
            if line.startswith(b"data: "):
                yield json.loads(line[6:])
    finally:
        conn.close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/":
            content = Path(__file__).with_name("ui.html").read_bytes()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(content)
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"live":true}')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        role = self.headers.get("Authorization", "").removeprefix("Bearer ")
        is_backend = self.server.server_port == 18782
        if is_backend:
            if role != "ui-fixture":
                self.send_error(403)
                return
            body["capability"] = capability("backend")
        elif role not in ("backend", "mihari", "mcp") or not valid(
            body.get("capability", {}), role
        ):
            self.send_error(403)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        detached = False

        def deliver(event):
            nonlocal detached
            if detached:
                return
            try:
                emit(self.wfile, event)
            except (BrokenPipeError, ConnectionResetError):
                detached = True

        try:
            if is_backend:
                for event in request_stream(18781, body):
                    deliver(event)
            else:
                row = run(body, deliver)
                with (ROOT / "server-requests.jsonl").open("a") as out:
                    out.write(
                        json.dumps(
                            {
                                "role": role,
                                "engine": body["engine"],
                                "path": body["path"],
                                **row,
                            }
                        )
                        + "\n"
                    )
        except (BrokenPipeError, ConnectionResetError):
            pass


def start(runtime):
    global ROOT, KEY, API, NATIVE
    ROOT = runtime
    ROOT.mkdir(parents=True, exist_ok=True)
    os.chmod(ROOT, 0o700)
    KEY = os.urandom(32)
    (ROOT / "fixture-key").write_bytes(KEY)
    os.chmod(ROOT / "fixture-key", 0o600)
    source = ROOT / "source"
    source.mkdir(exist_ok=True)
    (source / "worker.py").write_text("MAX_ATTEMPTS = 7\n")
    (source / "README.md").write_text(
        "PostgreSQL outbox with event_id idempotency. No deployment evidence.\n"
    )
    API = APIBridge()
    NATIVE = NativeRunner(ROOT / "calls")
    for port in (18781, 18782):
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    print("fixture services ready", flush=True)
    threading.Event().wait()


def mcp_loop(runtime):
    global KEY
    KEY = (runtime / "fixture-key").read_bytes()
    for line in sys.stdin:
        req = json.loads(line)
        method = req.get("method")
        result = {}
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "tsukai-routing-poc", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "ask_knowledge",
                        "description": "Answer a synthetic knowledge question through Tsukai",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"engine": {"type": "string"}},
                            "required": ["engine"],
                        },
                    }
                ]
            }
        elif method == "tools/call":
            engine = req["params"]["arguments"]["engine"]
            events = list(
                request_stream(
                    18781,
                    {
                        "engine": engine,
                        "path": "mcp",
                        "prompt": PROMPTS["mcp"],
                        "capability": capability("mcp"),
                    },
                    "mcp",
                )
            )
            result = {
                "content": [{"type": "text", "text": events[-1].get("text", "")}],
                "isError": not events[-1].get("success"),
            }
        if "id" in req:
            print(
                json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}),
                flush=True,
            )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("role", choices=["serve", "mcp"])
    p.add_argument("--runtime", type=Path, required=True)
    a = p.parse_args()
    if a.role == "serve":
        start(a.runtime)
    else:
        mcp_loop(a.runtime)
