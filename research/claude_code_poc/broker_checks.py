"""Real stream/concurrency probes for the isolated native Unix broker."""

import argparse
import collections
import json
import socket
import threading
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def request(payload, started=None):
        beginning = time.monotonic()
        counts = collections.Counter()
        first_text = None
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.connect(args.socket)
            connection.sendall((json.dumps(payload) + "\n").encode())
            if started:
                started.set()
            for line in connection.makefile("r"):
                event = json.loads(line)
                counts[event.get("type", "broker")] += 1
                if (
                    event.get("type") == "stream_event"
                    and event.get("event", {}).get("delta", {}).get("type")
                    == "text_delta"
                    and first_text is None
                ):
                    first_text = time.monotonic() - beginning
                if "broker_result" in event or "error" in event or "healthy" in event:
                    return {
                        "event": event,
                        "elapsed_s": time.monotonic() - beginning,
                        "first_text_s": first_text,
                        "event_counts": dict(counts),
                    }
        return {"error": "connection_closed"}

    checks = {}
    first = request(
        {
            "prompt": "For this conversation we adopted PostgreSQL outbox and event_id as the idempotency key. Acknowledge in one sentence."
        }
    )
    sid = first["event"]["session_id"]
    checks["first"] = first
    resumed = request(
        {
            "prompt": "What database pattern and idempotency key did we select?",
            "resume": sid,
        }
    )
    checks["stateful_recall"] = {
        "passed": "PostgreSQL" in resumed["event"]["broker_result"]
        and "event_id" in resumed["event"]["broker_result"],
        **resumed,
    }
    stateless = request(
        {
            "prompt": "Prior user decision: PostgreSQL outbox and event_id were adopted. What database pattern and key were chosen?"
        }
    )
    checks["stateless_recall"] = {
        "passed": "PostgreSQL" in stateless["event"]["broker_result"]
        and "event_id" in stateless["event"]["broker_result"],
        **stateless,
    }
    maintenance = request(
        {
            "prompt": "Use knowledge_base_search and code_graph_lookup to inspect worker.py. What is MAX_ATTEMPTS and idempotency key? Do not invent deployment evidence.",
            "maintenance": True,
        }
    )
    checks["maintenance"] = {
        "passed": "7" in maintenance["event"]["broker_result"]
        and "event_id" in maintenance["event"]["broker_result"],
        **maintenance,
    }
    started = threading.Event()
    active = {}

    def run():
        active["response"] = request(
            {
                "prompt": "Explain the adopted pattern and key in four paragraphs.",
                "resume": sid,
            },
            started,
        )

    thread = threading.Thread(target=run)
    thread.start()
    started.wait()
    time.sleep(0.15)
    health = request({"action": "health"})
    busy = request({"prompt": "What key did we choose?", "resume": sid})
    thread.join(timeout=120)
    checks["concurrent_health"] = {
        "passed": health["event"].get("healthy") and health["elapsed_s"] < 1,
        **health,
    }
    checks["same_session_lock"] = {
        "passed": busy["event"].get("error") == "session_busy",
        **busy,
    }
    checks["streaming"] = {
        "passed": first["first_text_s"] is not None
        and first["event_counts"].get("stream_event", 0) > 1,
        "first_text_s": first["first_text_s"],
        "events": first["event_counts"],
    }
    checks["session_id"] = sid
    args.output.write_text(json.dumps(checks, indent=2))
    print(json.dumps(checks, indent=2))


if __name__ == "__main__":
    main()
