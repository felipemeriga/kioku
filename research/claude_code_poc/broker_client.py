"""Container-side Unix socket probe. Contains no model credentials."""

import argparse
import json
import socket
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default="/broker/broker.sock")
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--resume")
    parser.add_argument(
        "--prompt",
        default="Answer one sentence: why is event_id useful for idempotency?",
    )
    args = parser.parse_args()
    request = (
        {"action": "health"}
        if args.health
        else {"prompt": args.prompt, "resume": args.resume}
    )
    started = time.monotonic()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.connect(args.socket)
        connection.sendall((json.dumps(request) + "\n").encode())
        stream = connection.makefile("r")
        for line in stream:
            event = json.loads(line)
            if args.health or "broker_result" in event:
                print(
                    json.dumps(
                        {"elapsed_s": time.monotonic() - started, "event": event}
                    ),
                    flush=True,
                )
                break


if __name__ == "__main__":
    main()
