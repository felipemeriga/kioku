"""Standalone localhost SSE chat POC, preserving generation after disconnect."""

import json
import queue
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from native import NativeRunner

ROOT = Path("/private/tmp/kioku-claude-poc-runtime/local-chat")
STATE = {}
LOCK = threading.Lock()
RUNNER = None


def generate(cid, content, mode, events):
    with LOCK:
        conversation = STATE.setdefault(
            cid, {"session_id": str(uuid.uuid4()), "history": [], "status": "idle"}
        )
        if conversation["status"] == "generating":
            events.put({"error": "Conversation already has an active turn"})
            events.put(None)
            return
        conversation["status"] = "generating"
        history = list(conversation["history"])
        sid = conversation["session_id"]

    def event(message):
        if message.get("type") == "stream_event":
            delta = message.get("event", {}).get("delta", {})
            if delta.get("type") == "text_delta":
                events.put({"token": delta["text"]})

    try:
        prompt = content
        if mode == "stateless":
            prompt = (
                "Conversation history:\n"
                + json.dumps(history)
                + "\nCurrent user request:\n"
                + content
            )
        result = RUNNER.call(
            f"http-chat-{mode}",
            prompt,
            persist=mode == "stateful",
            resume=sid if mode == "stateful" and history else None,
            session_id=sid if mode == "stateful" and not history else None,
            system_prompt="You are Kioku. Answer the user's repository design questions using supplied facts. Be concise and honest.",
            exclude_instructions=True,
            on_event=event,
        )
        with LOCK:
            conversation["history"] += [
                {"role": "user", "content": content},
                {"role": "assistant", "content": result.get("result") or ""},
            ]
            conversation["status"] = (
                "completed" if result["returncode"] == 0 else "error"
            )
            conversation["last_result"] = result["id"]
            (ROOT / "conversations.json").write_text(json.dumps(STATE, indent=2))
        if result["returncode"]:
            events.put({"error": result.get("subtype") or "native process failed"})
        events.put({"done": True})
    except Exception as exc:
        with LOCK:
            conversation["status"] = "error"
        events.put({"error": str(exc)[:300]})
    finally:
        events.put(None)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        events = queue.Queue()
        threading.Thread(
            target=generate,
            args=(body["conversation_id"], body["content"], body["mode"], events),
            daemon=True,
        ).start()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            while True:
                item = events.get(timeout=180)
                if item is None:
                    break
                self.wfile.write(("data: " + json.dumps(item) + "\n\n").encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # Generation thread persists independently.

    def do_GET(self):
        with LOCK:
            body = json.dumps(STATE).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def chat(base, cid, content, mode, abort_after_first=False):
    start = time.monotonic()
    request = urllib.request.Request(
        base + "/chat",
        data=json.dumps(
            {"conversation_id": cid, "content": content, "mode": mode}
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    result = {"text": "", "done": False, "first_token_s": None, "errors": []}
    with urllib.request.urlopen(request, timeout=180) as response:
        for line in response:
            if not line.startswith(b"data: "):
                continue
            event = json.loads(line[6:])
            if event.get("token"):
                if result["first_token_s"] is None:
                    result["first_token_s"] = time.monotonic() - start
                result["text"] += event["token"]
                if abort_after_first:
                    break
            if event.get("done"):
                result["done"] = True
            if event.get("error"):
                result["errors"].append(event["error"])
    result["elapsed_s"] = time.monotonic() - start
    return result


def main():
    global RUNNER
    ROOT.mkdir(parents=True, exist_ok=True)
    RUNNER = NativeRunner(ROOT / "calls")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    checks = []
    for mode in ["stateless", "stateful"]:
        cid = str(uuid.uuid4())
        first = chat(
            base,
            cid,
            "For the synthetic invoice worker we chose PostgreSQL outbox and event_id deduplication. Acknowledge in one sentence.",
            mode,
        )
        second = chat(
            base, cid, "What queue transport did we choose? One sentence.", mode
        )
        checks.append(
            {
                "mode": mode,
                "check": "http-roundtrip-and-recall",
                "passed": first["done"]
                and second["done"]
                and "PostgreSQL" in second["text"],
                "responses": [first, second],
            }
        )
    cid = str(uuid.uuid4())
    aborted = chat(
        base,
        cid,
        "Explain the source-grounded design tradeoffs of an invoice retry worker using PostgreSQL outbox. Write about250words.",
        "stateful",
        abort_after_first=True,
    )
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        with LOCK:
            complete = STATE[cid]["status"] == "completed"
            history = STATE[cid]["history"]
        if complete:
            break
        time.sleep(0.5)
    checks.append(
        {
            "mode": "stateful",
            "check": "disconnect-generation-persists",
            "passed": complete
            and len(history) == 2
            and len(history[-1]["content"]) > len(aborted["text"]),
            "client_partial_chars": len(aborted["text"]),
            "persisted_chars": len(history[-1]["content"]) if history else 0,
        }
    )
    server.shutdown()
    (ROOT / "checks.json").write_text(json.dumps(checks, indent=2))
    print(json.dumps(checks), flush=True)


if __name__ == "__main__":
    main()
