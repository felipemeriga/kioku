"""Measure public MCP memory tools with identical inputs across labeled controls.

Labels never enter tool arguments: these tools do not invoke a reasoning model.
Raw results and references are written only to a caller-selected private directory.
"""

import argparse
import asyncio
import hashlib
import json
import os
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def decode(result):
    if result.isError:
        raise ValueError("MCP tool returned an error")
    return json.loads(next(c.text for c in result.content if c.type == "text"))


def fingerprint(result, read=False):
    fields = (
        (
            "event_id",
            "record_sequence",
            "char_start",
            "excerpt",
            "has_more",
            "raw_record",
        )
        if read
        else ("folder_id", "session_id", "event_id", "record_sequence", "excerpt")
    )
    rows = [
        {key: row.get(key) for key in fields}
        for row in result.get("evidence" if read else "matches", [])
    ]
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def save(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, indent=2)


async def run(args):
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(args.output, 0o700)
    cfg = json.loads(args.config.read_text())["mcpServers"][args.server]
    url = cfg["url"].removesuffix("/sse").removesuffix("/mcp") + "/mcp"
    queries = json.loads(args.queries.read_text())
    rows = []
    async with (
        streamablehttp_client(url, headers=cfg["headers"], timeout=60) as (
            read,
            write,
            _,
        ),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        for index, query in enumerate(queries):
            for repeat in range(args.repeats):
                for control in ["low", "high"] if repeat % 2 else ["high", "low"]:
                    started = time.monotonic()
                    result = decode(
                        await session.call_tool("search_agent_history", query)
                    )
                    row = {
                        "case": index,
                        "repeat": repeat,
                        "control_label": control,
                        "search_seconds": time.monotonic() - started,
                        "search_fingerprint": fingerprint(result),
                        "search": result,
                    }
                    if result.get("matches"):
                        started = time.monotonic()
                        evidence = decode(
                            await session.call_tool(
                                "read_agent_evidence",
                                {
                                    "reference": result["matches"][0]["reference"],
                                    "before_records": 1,
                                    "after_records": 1,
                                    "char_limit": 2000,
                                },
                            )
                        )
                        row.update(
                            read_seconds=time.monotonic() - started,
                            read_fingerprint=fingerprint(evidence, True),
                            read=evidence,
                        )
                    rows.append(row)
                    save(args.output / "tools.json", rows)
                    print(
                        json.dumps(
                            {
                                key: value
                                for key, value in row.items()
                                if key not in {"search", "read"}
                            }
                        ),
                        flush=True,
                    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", type=Path, required=True)
    p.add_argument("--server", default="kioku")
    p.add_argument("--queries", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--repeats", type=int, default=3)
    args = p.parse_args()
    if not 1 <= args.repeats <= 10:
        p.error("Repeats must be between 1 and 10")
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
