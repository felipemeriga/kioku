"""Read-only synthetic MCP source, no network or production credentials."""

import ast
import json
import re
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
                terms = set(re.findall(r"[a-z_][a-z_0-9]{2,}", query.lower()))
                for path in sorted(root.rglob("*")):
                    if (
                        path.is_file()
                        and ".git" not in path.parts
                        and path.stat().st_size < 200000
                    ):
                        relative = str(path.relative_to(root))
                        source = path.read_text()
                        if (
                            request.get("params", {}).get("name") == "code_graph_lookup"
                            and path.suffix == ".py"
                        ):
                            try:
                                tree = ast.parse(source)
                            except SyntaxError:
                                continue
                            for node in ast.walk(tree):
                                if isinstance(
                                    node,
                                    (
                                        ast.FunctionDef,
                                        ast.AsyncFunctionDef,
                                        ast.ClassDef,
                                    ),
                                ):
                                    calls = [
                                        ast.unparse(item.func)
                                        for item in ast.walk(node)
                                        if isinstance(item, ast.Call)
                                    ][:15]
                                    text = f"[1] {relative}:{node.lineno} definition {node.name}; calls: {', '.join(calls)}"
                                    evidence.append(
                                        (
                                            sum(term in text.lower() for term in terms),
                                            text,
                                        )
                                    )
                        else:
                            lines = source.splitlines()
                            for offset in range(0, len(lines), 45):
                                text = f"[1] {relative}:{offset + 1}\n" + "\n".join(
                                    lines[offset : offset + 60]
                                )
                                evidence.append(
                                    (sum(term in text.lower() for term in terms), text)
                                )
                evidence.sort(key=lambda item: item[0], reverse=True)
                result = {
                    "content": [
                        {
                            "type": "text",
                            "text": "\n\n".join(text for _, text in evidence[:8])[
                                :22000
                            ],
                        }
                    ]
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
