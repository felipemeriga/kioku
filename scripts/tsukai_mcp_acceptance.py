"""Real MCP SDK client probe; never run against a mocked transport.

Private JSON config: {"url": "https://host/mcp", "token_file": "/private/key",
"folder_name": "tsukai-e2e-...", "expected_marker": "fixture marker",
"evidence": "/private/results.jsonl"}. Token files must be mode 0600.
Use --metadata for an actual generative metadata call plus concurrent schema
responsiveness check. Credentials and retrieved private content are not printed.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import stat
import time
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def text_content(result):
    if result.isError:
        raise RuntimeError("MCP tool returned isError")
    text = "\n".join(item.text for item in result.content if item.type == "text")
    if not text.strip():
        raise RuntimeError("MCP tool returned no text")
    return text


async def probe(config, metadata=False):
    if not config["folder_name"].startswith("tsukai-e2e-"):
        raise ValueError("An isolated tsukai-e2e-* scope is required")
    if not config["expected_marker"].strip():
        raise ValueError("A nonempty expected fixture marker is required")
    token_path = Path(config["token_file"])
    if stat.S_IMODE(token_path.stat().st_mode) != 0o600:
        raise ValueError("MCP token file must be mode 0600")
    headers = {"Authorization": "Bearer " + token_path.read_text().strip()}
    began = time.monotonic()
    async with streamablehttp_client(
        config["url"], headers=headers, timeout=30, sse_read_timeout=180
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = {tool.name for tool in tools.tools}
            required = {"get_folder_briefing_schema", "get_folder_briefing"}
            if not required.issubset(names):
                raise RuntimeError(
                    "Expected Kioku tools missing from actual MCP server"
                )
            schema = text_content(
                await session.call_tool("get_folder_briefing_schema", {})
            )
            if "overview" not in schema:
                raise RuntimeError("Briefing schema did not contain overview")
            briefing = text_content(
                await session.call_tool(
                    "get_folder_briefing", {"folder": config["folder_name"]}
                )
            )
            if config["expected_marker"] not in briefing:
                raise RuntimeError(
                    "Actual scoped briefing lacks expected fixture marker"
                )
            result = {
                "kind": "real_mcp",
                "tool_count": len(names),
                "briefing_sha256": hashlib.sha256(briefing.encode()).hexdigest(),
                "metadata": metadata,
            }
            if metadata:
                pending = asyncio.create_task(
                    session.call_tool(
                        "query_documents_metadata",
                        {"question": "Count documents in this scope."},
                    )
                )
                concurrent_began = time.monotonic()
                concurrent = text_content(
                    await session.call_tool("get_folder_briefing_schema", {})
                )
                result["concurrent_schema_seconds"] = (
                    time.monotonic() - concurrent_began
                )
                result["metadata_pending_during_schema"] = not pending.done()
                if (
                    "overview" not in concurrent
                    or result["concurrent_schema_seconds"] > 10
                ):
                    raise RuntimeError(
                        "Schema responsiveness failed during metadata request"
                    )
                answer = text_content(await pending)
                parsed = json.loads(answer)
                if parsed.get("operation") != "count_files" or not isinstance(
                    parsed.get("data", {}).get("count"), int
                ):
                    raise RuntimeError(
                        "Native typed metadata count response is missing"
                    )
                if (
                    "expected_document_count" in config
                    and parsed["data"]["count"] != config["expected_document_count"]
                ):
                    raise RuntimeError("Metadata count disagrees with isolated fixture")
                if not result["metadata_pending_during_schema"]:
                    raise RuntimeError(
                        "Concurrent schema call did not overlap metadata work"
                    )
                result["metadata_sha256"] = hashlib.sha256(answer.encode()).hexdigest()
    result["elapsed_seconds"] = time.monotonic() - began
    evidence = Path(config["evidence"])
    descriptor = os.open(evidence, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "a") as stream:
        stream.write(json.dumps(result, sort_keys=True) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--metadata", action="store_true")
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    try:
        result = asyncio.run(probe(json.loads(args.config.read_text()), args.metadata))
    except Exception:
        # SDK exception trees may contain headers or response bodies. Preserve
        # only the exit status here; investigate privately in the real services.
        print('{"ok": false, "kind": "real_mcp"}')
        raise SystemExit(1) from None
    print(json.dumps({"ok": True, **result}, sort_keys=True))


if __name__ == "__main__":
    main()
