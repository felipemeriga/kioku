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


class CheckFailure(RuntimeError):
    """A sanitized acceptance assertion with no service response body."""


def safe_assertions(error):
    if isinstance(error, CheckFailure):
        return [str(error)]
    return [
        message
        for child in getattr(error, "exceptions", ())
        for message in safe_assertions(child)
    ]


def text_content(result):
    if result.isError:
        raise CheckFailure("MCP tool returned isError")
    text = "\n".join(item.text for item in result.content if item.type == "text")
    if not text.strip():
        raise CheckFailure("MCP tool returned no text")
    if text.lstrip().lower().startswith(("error:", "query failed:", "error reading")):
        raise CheckFailure("MCP tool returned a textual service error")
    return text


async def probe(config, metadata=False, surfaces=False):
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
                raise CheckFailure(
                    "Expected Kioku tools missing from actual MCP server"
                )
            schema = text_content(
                await session.call_tool("get_folder_briefing_schema", {})
            )
            if "overview" not in schema:
                raise CheckFailure("Briefing schema did not contain overview")
            briefing = text_content(
                await session.call_tool(
                    "get_folder_briefing", {"folder": config["folder_name"]}
                )
            )
            identity = json.loads(briefing).get("folder")
            if isinstance(identity, dict):
                identity = identity.get("name")
            if identity != config["folder_name"]:
                raise CheckFailure(
                    "Actual briefing identity differs from the exact fixture name"
                )
            scope_listing = json.loads(
                text_content(await session.call_tool("list_folders_in_scope", {}))
            )
            if scope_listing.get("scope_folder_id") != config["folder_id"]:
                raise CheckFailure(
                    "Actual MCP API key scope differs from the exact fixture UUID"
                )
            result = {
                "kind": "real_mcp",
                "tool_count": len(names),
                "briefing_sha256": hashlib.sha256(briefing.encode()).hexdigest(),
                "metadata": metadata,
                "fixture_identity_verified": True,
            }
            if surfaces:
                folder = config["folder_name"]
                symbol = config.get("graph_symbol", "run_once")
                path = config.get("graph_path", "worker.py")
                calls = [
                    ("get_folder_orientation", {"folder": folder}, folder),
                    ("list_folders_in_scope", {}, folder),
                    (
                        "read_folder_documents",
                        {"folder": folder},
                        config["expected_marker"],
                    ),
                    ("get_repo_documentation", {"folder": folder}, None),
                    (
                        "knowledge_base_search",
                        {"folder": folder, "query": config["expected_marker"]},
                        config["expected_marker"],
                    ),
                    ("outline", {"folder": folder, "path": path}, symbol),
                    ("find_definition", {"folder": folder, "symbol": symbol}, path),
                    ("find_references", {"folder": folder, "symbol": symbol}, path),
                    (
                        "impact_of",
                        {"folder": folder, "symbol": symbol, "depth": 2},
                        path,
                    ),
                    (
                        "code_search",
                        {
                            "folder": folder,
                            "query": "poll pending SQLite reminders and deliver each reminder",
                            "language": "python",
                            "top_k": 3,
                        },
                        path,
                    ),
                ]
                result["surfaces"] = []
                for name, arguments, expected in calls:
                    if name not in names:
                        raise CheckFailure(
                            "Required real MCP read surface is missing: " + name
                        )
                    started = time.monotonic()
                    value = await session.call_tool(name, arguments)
                    try:
                        answer = text_content(value)
                    except CheckFailure:
                        raise CheckFailure(
                            "Actual MCP read surface returned an error: " + name
                        ) from None
                    available = not answer.startswith("No documentation saved yet")
                    if expected and expected not in answer:
                        raise CheckFailure(
                            "Actual MCP read surface lacks fixture evidence: " + name
                        )
                    result["surfaces"].append(
                        {
                            "name": name,
                            "available": available,
                            "seconds": time.monotonic() - started,
                            "sha256": hashlib.sha256(answer.encode()).hexdigest(),
                        }
                    )
                    descriptor = os.open(
                        config["evidence"],
                        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                        0o600,
                    )
                    with os.fdopen(descriptor, "a") as stream:
                        stream.write(
                            json.dumps(
                                {
                                    "kind": "real_mcp_surface",
                                    "ok": True,
                                    **result["surfaces"][-1],
                                },
                                sort_keys=True,
                            )
                            + "\n"
                        )
                        stream.flush()
                        os.fsync(stream.fileno())
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
                    raise CheckFailure(
                        "Schema responsiveness failed during metadata request"
                    )
                answer = text_content(await pending)
                parsed = json.loads(answer)
                if parsed.get("operation") != "count_files" or not isinstance(
                    parsed.get("data", {}).get("count"), int
                ):
                    raise CheckFailure(
                        "Native typed metadata count response is missing"
                    )
                if (
                    "expected_document_count" in config
                    and parsed["data"]["count"] != config["expected_document_count"]
                ):
                    raise CheckFailure("Metadata count disagrees with isolated fixture")
                if not result["metadata_pending_during_schema"]:
                    raise CheckFailure(
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
    parser.add_argument(
        "--surfaces",
        action="store_true",
        help="Read all fixture document/search/graph surfaces after real indexing",
    )
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    config = {}
    try:
        config = json.loads(args.config.read_text())
        result = asyncio.run(probe(config, args.metadata, args.surfaces))
    except Exception as exc:
        # SDK exception trees may contain headers or response bodies. Preserve
        # only the exit status here; investigate privately in the real services.
        failure = {
            "ok": False,
            "kind": "real_mcp",
            "reason": str(exc) if isinstance(exc, CheckFailure) else type(exc).__name__,
        }
        failure["assertions"] = safe_assertions(exc)
        if config.get("evidence"):
            descriptor = os.open(
                config["evidence"], os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600
            )
            with os.fdopen(descriptor, "a") as stream:
                stream.write(json.dumps(failure, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        print(json.dumps(failure))
        raise SystemExit(1) from None
    print(json.dumps({"ok": True, **result}, sort_keys=True))


if __name__ == "__main__":
    main()
