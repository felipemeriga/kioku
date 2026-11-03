"""Local-only native Claude process adapter. Never reads credentials."""

import json
import os
import signal
import subprocess
import threading
import time
import uuid
from pathlib import Path


class NativeRunner:
    def __init__(self, runtime: Path):
        self.runtime = runtime
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()

    def call(
        self,
        label,
        prompt,
        *,
        resume=None,
        session_id=None,
        model="haiku",
        persist=True,
        timeout=180,
        mcp=None,
        schema=None,
        kill_after=None,
        system_prompt=None,
        safe_mode=False,
        exclude_instructions=False,
    ):
        call_id = f"{time.time_ns()}-{uuid.uuid4().hex[:6]}"
        directory = self.runtime / call_id
        directory.mkdir()
        args = [
            "claude",
            "-p",
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
            json.dumps(mcp or {"mcpServers": {}}),
            "--tools",
            "",
            "--disable-slash-commands",
            "--no-chrome",
            "--model",
            model,
            "--effort",
            "low",
            "--max-turns",
            "8",
        ]
        if exclude_instructions:
            settings_index = args.index("--settings") + 1
            args[settings_index] = json.dumps(
                {
                    "disableAllHooks": True,
                    "claudeMdExcludes": [
                        "**/CLAUDE.md",
                        "**/AGENTS.md",
                        "**/CLAUDE.local.md",
                        "**/.claude/rules/**",
                    ],
                }
            )
        if resume:
            args += ["--resume", resume]
        elif session_id:
            args += ["--session-id", session_id]
        if not persist:
            args += ["--no-session-persistence"]
        if mcp:
            args += [
                "--allowedTools",
                "mcp__fixture__knowledge_base_search",
                "mcp__fixture__code_graph_lookup",
            ]
        if schema:
            args += ["--json-schema", json.dumps(schema)]
        if system_prompt:
            args += ["--system-prompt", system_prompt]
        if safe_mode:
            args += ["--safe-mode"]
        env = os.environ.copy()
        # Force the native signed-in route; no API/provider credential fallback.
        for key in list(env):
            if key.startswith(("ANTHROPIC_", "CLAUDE_CODE_USE_")):
                env.pop(key)
        env["CLAUDE_CODE_DISABLE_BACKGROUND_TASKS"] = "1"
        env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
        started = time.monotonic()
        record = {
            "id": call_id,
            "label": label,
            "model_requested": model,
            "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "resume": resume,
            "persist": persist,
        }
        events = []
        with (directory / "stderr.txt").open("w") as stderr:
            process = subprocess.Popen(
                args,
                cwd=self.runtime,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr,
                text=True,
                start_new_session=True,
                bufsize=1,
            )
            process.stdin.write(prompt)
            process.stdin.close()

            def terminate():
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass

            timer = threading.Timer(kill_after or timeout, terminate)
            timer.start()
            try:
                with (directory / "events.jsonl").open("w") as output:
                    for line in process.stdout:
                        output.write(line)
                        output.flush()
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        events.append(event)
                        if "first_event_s" not in record:
                            record["first_event_s"] = time.monotonic() - started
                        if event.get("type") == "stream_event":
                            delta = event.get("event", {}).get("delta", {})
                            if (
                                delta.get("type") == "text_delta"
                                and "first_text_s" not in record
                            ):
                                record["first_text_s"] = time.monotonic() - started
                    process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            finally:
                timer.cancel()
                process.stdout.close()
        result = next((e for e in reversed(events) if e.get("type") == "result"), {})
        record.update(
            {
                "elapsed_s": round(time.monotonic() - started, 3),
                "returncode": process.returncode,
                "result": result.get("result"),
                "structured_output": result.get("structured_output"),
                "session_id": result.get("session_id"),
                "is_error": result.get("is_error", not bool(result)),
                "terminal_result_seen": bool(result),
                "subtype": result.get("subtype"),
                "usage": result.get("usage"),
                "list_cost_usd": result.get("total_cost_usd"),
                "model_usage": result.get("modelUsage"),
                "num_turns": result.get("num_turns"),
                "permission_denials": result.get("permission_denials"),
                "event_count": len(events),
                "event_types": sorted({e.get("type", "unknown") for e in events}),
                "forced_cancel": bool(kill_after),
            }
        )
        with self.lock, (self.runtime / "calls.jsonl").open("a") as target:
            target.write(json.dumps(record) + "\n")
        return record
