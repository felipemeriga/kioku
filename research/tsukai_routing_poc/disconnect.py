"""Verify disconnect detaches delivery while native stdout continues draining."""

import http.client
import json
import sys
import time
from pathlib import Path

import poc

root = Path(sys.argv[1])
poc.KEY = (root / "fixture-key").read_bytes()
conn = http.client.HTTPConnection("127.0.0.1", 18782, timeout=90)
conn.request(
    "POST",
    "/invoke",
    json.dumps(
        {
            "engine": "native",
            "path": "disconnect",
            "prompt": "Using supplied fact MAX_ATTEMPTS=7 and event_id deduplication, write six numbered practical explanations. Do not invent implementation details.",
        }
    ),
    {"Authorization": "Bearer ui-fixture", "Content-Type": "application/json"},
)
response = conn.getresponse()
first = response.readline()
response.close()
conn.close()
health = http.client.HTTPConnection("127.0.0.1", 18782)
started = time.monotonic()
health.request("GET", "/health")
status = health.getresponse().status
health_s = time.monotonic() - started
health.close()
deadline = time.monotonic() + 45
completed = None
while time.monotonic() < deadline:
    rows = [
        json.loads(s) for s in (root / "server-requests.jsonl").read_text().splitlines()
    ]
    completed = next((r for r in reversed(rows) if r["path"] == "disconnect"), None)
    if completed:
        break
    time.sleep(0.2)
result = {
    "first_stream_event_received": bool(first),
    "health_status": status,
    "health_s": health_s,
    "generation_completed_after_disconnect": bool(
        completed and completed["result"]["success"]
    ),
    "answer_chars": len(completed["result"].get("text", "")) if completed else 0,
    "durable_replay_implemented": False,
}
(root / "disconnect.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result))
