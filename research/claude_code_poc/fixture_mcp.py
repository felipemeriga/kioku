"""Read-only synthetic MCP source, no network or production credentials."""

import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
for line in sys.stdin:
    try:
        request = json.loads(line)
        method = request.get("method")
        result = {}
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fixture", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": name,
                        "description": description,
                        "inputSchema": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                            "required": ["query"],
                        },
                    }
                    for name, description in [
                        (
                            "knowledge_base_search",
                            "Read source-grounded facts from the current repository. Returns [1] citations.",
                        ),
                        (
                            "code_graph_lookup",
                            "Read exact source definitions and callers from the current repository.",
                        ),
                    ]
                ]
            }
        elif method == "tools/call":
            query = request.get("params", {}).get("arguments", {}).get("query", "")
            if "INJECT_TOOL_FAILURE" in query:
                result = {
                    "isError": True,
                    "content": [
                        {
                            "type": "text",
                            "text": "Fixture retrieval unavailable; do not invent evidence.",
                        }
                    ],
                }
            else:
                evidence = []
                for path in sorted(root.rglob("*")):
                    if (
                        path.is_file()
                        and ".git" not in path.parts
                        and path.stat().st_size < 30000
                    ):
                        evidence.append(
                            f"[1] {path.relative_to(root)}\n{path.read_text()}"
                        )
                result = {
                    "content": [{"type": "text", "text": "\n\n".join(evidence)[:22000]}]
                }
        elif method == "ping":
            result = {}
        if "id" in request:
            print(
                json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}),
                flush=True,
            )
    except Exception as exc:
        print(str(exc), file=sys.stderr, flush=True)
