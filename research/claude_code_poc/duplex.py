"""Persistent stream-json input/output experiment with explicit-session recovery."""

import json
import os
import queue
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path


class DuplexSession:
    def __init__(self, runtime: Path, session_id: str, resume: bool = False):
        self.session_id = session_id
        self.messages = queue.Queue()
        self.runtime = runtime
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.log = (runtime / f"duplex-{time.time_ns()}.jsonl").open("w")
        self.stderr = (runtime / "duplex.stderr").open("a")
        env = os.environ.copy()
        for name in list(env):
            if name.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_")):
                env.pop(name)
        env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] = "1"
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
        args = [
            "claude",
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--setting-sources",
            "",
            "--settings",
            '{"disableAllHooks":true}',
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--tools",
            "",
            "--disable-slash-commands",
            "--no-chrome",
            "--model",
            "haiku",
            "--effort",
            "low",
            "--resume" if resume else "--session-id",
            session_id,
        ]
        self.process = subprocess.Popen(
            args,
            cwd=runtime,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.stderr,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.process.stdout:
            self.log.write(line)
            self.log.flush()
            try:
                self.messages.put(json.loads(line))
            except json.JSONDecodeError:
                pass
        self.messages.put({"type": "process_exit", "returncode": self.process.wait()})

    def ask(self, prompt, timeout=150):
        start = time.monotonic()
        self.process.stdin.write(
            json.dumps(
                {
                    "type": "user",
                    "session_id": self.session_id,
                    "message": {"role": "user", "content": prompt},
                }
            )
            + "\n"
        )
        self.process.stdin.flush()
        first_text = None
        while True:
            event = self.messages.get(
                timeout=max(0.1, timeout - (time.monotonic() - start))
            )
            if event.get("type") == "stream_event":
                delta = event.get("event", {}).get("delta", {})
                if delta.get("type") == "text_delta" and first_text is None:
                    first_text = time.monotonic() - start
            if event.get("type") == "process_exit":
                raise RuntimeError(f"CLI exited: {event['returncode']}")
            if event.get("type") == "result":
                return {
                    "elapsed_s": round(time.monotonic() - start, 3),
                    "first_text_s": first_text,
                    "result": event.get("result"),
                    "session_id": event.get("session_id"),
                    "usage": event.get("usage"),
                    "list_cost_usd": event.get("total_cost_usd"),
                    "is_error": event.get("is_error"),
                    "pid": self.process.pid,
                }

    def close(self, force=False):
        if self.process.poll() is None:
            if force:
                os.killpg(self.process.pid, signal.SIGKILL)
            else:
                self.process.stdin.close()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
        self.stderr.close()


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--duration", type=int, default=10800)
    args = parser.parse_args()
    root = args.runtime.resolve()
    root.mkdir(parents=True, exist_ok=True)
    sid = str(uuid.uuid4())
    session = DuplexSession(root, sid)
    started = time.monotonic()
    state = {
        "start_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_id": sid,
        "turns": [],
        "status": "running",
    }
    index = 0
    expected = "Redis Streams"
    while time.monotonic() - started < args.duration:
        if index == 0:
            prompt = (
                "We are designing a synthetic invoice worker. We selected Redis Streams as the "
                "queue transport and event_id as the idempotency key. Summarize this decision "
                "in one sentence; these are ordinary fixture architecture choices."
            )
        elif index % 10 == 0:
            expected = "PostgreSQL outbox" if index % 20 else "Redis Streams"
            prompt = (
                f"The architecture decision has changed: use {expected} as the queue transport. "
                "The idempotency key remains event_id. Summarize the current choice in one sentence."
            )
        else:
            prompt = (
                "Which queue transport did we most recently choose for this invoice worker, "
                "and what is its idempotency key? Answer in one sentence from this conversation."
            )
        try:
            if index and index % 15 == 0:
                session.close(force=True)
                session = DuplexSession(root, sid, resume=True)
            result = session.ask(prompt)
            result.update(
                index=index,
                recall_correct=expected in (result["result"] or ""),
                elapsed_since_start_s=round(time.monotonic() - started, 3),
            )
            state["turns"].append(result)
        except Exception as exc:
            state["turns"].append({"index": index, "error": str(exc)[:400]})
            session.close(force=True)
            session = DuplexSession(root, sid, resume=True)
        state["elapsed_s"] = round(time.monotonic() - started, 3)
        (root / "duplex-checkpoint.json").write_text(json.dumps(state, indent=2))
        print(json.dumps(state["turns"][-1]), flush=True)
        index += 1
        next_start = min(started + index * 180, started + args.duration)
        while time.monotonic() < next_start:
            time.sleep(min(20, next_start - time.monotonic()))
    session.close()
    state.update(
        status="completed",
        elapsed_s=round(time.monotonic() - started, 3),
        finished_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )
    (root / "duplex-checkpoint.json").write_text(json.dumps(state, indent=2))


if __name__ == "__main__":
    main()
