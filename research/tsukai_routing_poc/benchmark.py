"""Interleaved small-sample latency comparison; never infers invoice spend."""

import argparse
import json
import random
import subprocess
import sys
import time
from pathlib import Path

import poc


def measure(path, engine, runtime, prompt=None):
    started = time.monotonic()
    first = None
    events = []
    if path == "mcp":
        process = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).with_name("poc.py")),
                "mcp",
                "--runtime",
                str(runtime),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        for req in [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "poc-client", "version": "1"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "ask_knowledge", "arguments": {"engine": engine}},
            },
        ]:
            process.stdin.write(json.dumps(req) + "\n")
            process.stdin.flush()
            if "id" in req:
                response = json.loads(process.stdout.readline())
        process.stdin.close()
        process.wait(timeout=5)
        result = {
            "success": not response["result"].get("isError"),
            "text": response["result"]["content"][0]["text"],
        }
    else:
        body = {
            "engine": engine,
            "path": path,
            "prompt": prompt or poc.PROMPTS[path],
            "capability": poc.capability("backend" if path == "chat" else "mihari"),
        }
        for event in poc.request_stream(
            18782 if path == "chat" else 18781,
            body,
            "ui-fixture" if path == "chat" else "mihari",
        ):
            events.append(event)
            if event.get("type") == "text" and first is None:
                first = time.monotonic() - started
        result = events[-1]
    return {
        "path": path,
        "engine": engine,
        "total_s": time.monotonic() - started,
        "first_text_s": first,
        "result": result,
        "observed_events": len(events),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    args = parser.parse_args()
    runtime = args.runtime
    poc.KEY = (runtime / "fixture-key").read_bytes()
    output = runtime / "benchmarks.jsonl"
    jobs = [
        (path, engine, repeat)
        for repeat in range(5)
        for path in ("chat", "mihari", "mcp")
        for engine in ("native", "api")
    ]
    random.Random(711).shuffle(jobs)
    for path, engine, repeat in jobs:
        row = measure(path, engine, runtime)
        row["repeat"] = repeat
        with output.open("a") as stream:
            stream.write(json.dumps(row) + "\n")
        print(
            json.dumps(
                {
                    "path": path,
                    "engine": engine,
                    "repeat": repeat,
                    "total_s": round(row["total_s"], 3),
                    "first_text_s": row["first_text_s"],
                    "success": row["result"]["success"],
                }
            ),
            flush=True,
        )
    api = poc.APIBridge()
    for repeat in range(5):
        started = time.monotonic()
        texts = []

        def callback(event, texts=texts, started=started):
            if event["type"] == "text":
                texts.append(time.monotonic() - started)

        result = api.call(
            {"model": poc.MODEL, "system": poc.SYSTEM, "prompt": poc.PROMPTS["chat"]},
            callback,
        )
        row = {
            "path": "api_direct",
            "engine": "api",
            "repeat": repeat,
            "total_s": time.monotonic() - started,
            "first_text_s": texts[0] if texts else None,
            "result": result,
        }
        with output.open("a") as stream:
            stream.write(json.dumps(row) + "\n")
    api.process.terminate()
    mocks = []
    for path in ("chat", "mihari", "mcp"):
        for _ in range(10):
            mocks.append(measure(path, "mock", runtime))
    (runtime / "routing-overhead.json").write_text(json.dumps(mocks, indent=2))


if __name__ == "__main__":
    main()
