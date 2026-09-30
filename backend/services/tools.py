"""Tool definitions and dispatch for agentic RAG."""

import json

from langsmith import traceable

from db.client import get_supabase
from services.embeddings import embed_query
from services.repo_graph import store as graph_store
from services.search import search_documents
from services.text_to_sql import generate_and_execute_sql
from services.web_search import web_search

TOOL_DEFINITIONS = [
    {
        "name": "knowledge_base_search",
        "description": (
            "Search the user's uploaded document knowledge base using hybrid "
            "vector + keyword search. Use this for questions about content in "
            "the user's documents."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to find relevant document chunks.",
                },
                "created_after": {
                    "type": "string",
                    "description": (
                        "Optional ISO date (YYYY-MM-DD). Only search content created "
                        "on/after this date — use when the user asks about a specific "
                        "period ('last month', 'since March', 'recent')."
                    ),
                },
                "created_before": {
                    "type": "string",
                    "description": (
                        "Optional ISO date (YYYY-MM-DD). Only search content created "
                        "on/before this date — use for historical questions "
                        "('back in January', 'before the migration')."
                    ),
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "query_documents_metadata",
        "description": (
            "Query structured metadata about the user's uploaded documents using "
            "natural language. Use this for questions like 'how many documents do I have', "
            "'what topics are covered', 'list my PDFs', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Natural language question about document metadata.",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "web_search",
        "description": (
            "Search the web for information not found in the user's knowledge base. "
            "Use this when the knowledge base doesn't contain relevant information "
            "to answer the user's question."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The web search query.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "code_graph_lookup",
        "description": (
            "Look up EXACT code symbols in the indexed code graph (AST, not semantic "
            "similarity). Searches every repository in scope, so it answers cross-repo "
            "structural questions precisely. Prefer this over knowledge_base_search when "
            "the user names a specific function/class/method and wants exact structure:\n"
            "  • definition — where a symbol is defined (file:line)\n"
            "  • references — who calls / references a symbol (call sites)\n"
            "  • impact — transitive callers, i.e. blast radius of changing a symbol\n"
            "  • outline — every symbol under a file or directory path\n"
            "Examples: 'where is update_phase defined', 'who calls createGameCameras', "
            "'what breaks if I change embed_query', 'outline the ses/ingester folder'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["definition", "references", "impact", "outline"],
                    "description": (
                        "definition = where a symbol is defined; references = who "
                        "calls/uses it; impact = transitive callers (blast radius); "
                        "outline = all symbols under a file/directory path."
                    ),
                },
                "symbol": {
                    "type": "string",
                    "description": (
                        "Symbol name (function/class/method) for definition, references, "
                        "or impact. Bare name — no parentheses or module prefix."
                    ),
                },
                "path": {
                    "type": "string",
                    "description": "File or directory path prefix for the outline operation.",
                },
            },
            "required": ["operation"],
        },
    },
]

# Cap the graph tool's output so a hot symbol (thousands of call sites) can't
# flood the model's context; the model can narrow the query if it needs more.
_GRAPH_MAX_LINES = 100


def _folder_names(sb, folder_ids: list[str]) -> dict[str, str]:
    """Map folder_id -> repo name for labeling cross-repo graph results."""
    if not folder_ids:
        return {}
    rows = (sb.table("folders").select("id,name").in_("id", folder_ids).execute().data) or []
    return {r["id"]: r["name"] for r in rows}


def _code_graph_lookup(tool_input: dict, scope_folder_ids: list[str] | None) -> str:
    """Query the code graph across every repo in scope. Symbols/edges are
    per-folder, so we fan out over the scope folders and label each hit with
    its repo — that's what makes the lookup cross-repo."""
    op = (tool_input.get("operation") or "").strip()
    symbol = (tool_input.get("symbol") or "").strip()
    path = (tool_input.get("path") or "").strip()
    folders = scope_folder_ids or []
    if not folders:
        return "No repositories are in scope to search the code graph."
    if op in ("definition", "references", "impact") and not symbol:
        return f"The '{op}' operation needs a 'symbol'."
    if op == "outline" and not path:
        return "The 'outline' operation needs a 'path'."

    sb = get_supabase()
    names = _folder_names(sb, folders)
    lines: list[str] = []
    for fid in folders:
        repo = names.get(fid, fid)
        if op == "definition":
            for r in graph_store.find_definition(sb, folder_id=fid, symbol=symbol):
                lines.append(f"[{repo}] {r['kind']} {r['symbol']} — {r['file']}:{r['start_line']}")
        elif op == "references":
            for r in graph_store.find_references(sb, folder_id=fid, symbol=symbol):
                lines.append(f"[{repo}] {r['relation']} at {r['ref_file']}:{r['ref_line']}")
        elif op == "impact":
            for r in graph_store.impact_of(sb, folder_id=fid, symbol=symbol):
                lines.append(
                    f"[{repo}] depth {r['depth']}: {r['symbol']} — {r['file']}:{r['start_line']}"
                )
        elif op == "outline":
            for r in graph_store.outline(sb, folder_id=fid, path=path):
                lines.append(f"[{repo}] {r['kind']} {r['symbol']} — {r['file']}:{r['start_line']}")
        else:
            return f"Unknown code_graph_lookup operation: '{op}'."

    if not lines:
        target = symbol or path
        return f"No code-graph results for '{target}' ({op}) in the repositories in scope."
    if len(lines) > _GRAPH_MAX_LINES:
        extra = len(lines) - _GRAPH_MAX_LINES
        return "\n".join(lines[:_GRAPH_MAX_LINES]) + f"\n… (+{extra} more — narrow the query)"
    return "\n".join(lines)


@traceable(name="execute_tool", run_type="tool")
def execute_tool(
    tool_name: str,
    tool_input: dict,
    user_id: str,
    topic: str | None = None,
    keyword: str | None = None,
    fast_mode: bool = False,
    scope_folder_ids: list[str] | None = None,
    scope_filename: str | None = None,
) -> str:
    """Execute a tool call and return the result as a string."""
    if tool_name == "knowledge_base_search":
        query = tool_input["query"]
        embedding = embed_query(query)
        results = search_documents(
            embedding,
            query_text=query,
            user_id=user_id,
            topic=topic,
            keyword=keyword,
            fast_mode=fast_mode,
            folder_ids=scope_folder_ids,
            source_filename=scope_filename,
            created_after=tool_input.get("created_after"),
            created_before=tool_input.get("created_before"),
        )
        if not results:
            return "No relevant documents found in the knowledge base."
        chunks = []
        for r in results:
            meta = r.get("metadata") or {}
            source = meta.get("source_filename", "unknown")
            if r.get("source_type") == "code":
                # Code hits are actual source, not documentation — label them so
                # the model can distinguish ground truth from narrative.
                symbol = meta.get("code_symbol")
                header = f"[Code: {source} — {symbol}]" if symbol else f"[Code: {source}]"
            else:
                # Date in the header lets the model weigh freshness and cite
                # as-of dates — retrieval alone can't resolve conflicting facts.
                date = str(r.get("created_at") or "")[:10]
                header = f"[Source: {source} — {date}]" if date else f"[Source: {source}]"
            chunks.append(f"{header}\n{r['content']}")
        return "\n\n---\n\n".join(chunks)

    if tool_name == "query_documents_metadata":
        result = generate_and_execute_sql(tool_input["question"], user_id)
        if result["error"]:
            return f"Query failed: {result['error']}"
        if not result["results"]:
            return "No results found."
        return f"SQL: {result['sql']}\nResults: {json.dumps(result['results'], default=str)}"

    if tool_name == "web_search":
        results = web_search(tool_input["query"])
        if not results:
            return "Web search returned no results."
        parts = []
        for r in results:
            parts.append(f"**{r['title']}**\n{r['url']}\n{r['content']}")
        return "\n\n---\n\n".join(parts)

    if tool_name == "code_graph_lookup":
        return _code_graph_lookup(tool_input, scope_folder_ids)

    return f"Unknown tool: {tool_name}"
