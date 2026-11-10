"""Tool definitions and dispatch for agentic RAG."""

import json

from langsmith import traceable

from db.client import get_supabase_thread_safe
from db.client import get_supabase_thread_safe as get_supabase
from services.agent_memory_tools import DEFINITIONS as MEMORY_TOOL_DEFINITIONS
from services.citations import CitationRegistry
from services.embeddings import embed_query
from services.folder_summary.repo import get_latest_summary
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
                        "or impact. Prefer the full indexed symbol when known; bare names "
                        "are also accepted. Empty results may include definition suggestions."
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
    {
        "name": "recent_changes",
        "description": (
            "Get a digest of what has CHANGED RECENTLY in the repositories in scope — "
            "recent-commit themes and highlights (with PR numbers) distilled from git "
            "history and kept current by the indexer. Use this for 'what changed / what's "
            "new / recent work / latest updates' questions. Semantic search over the code "
            "shows the CURRENT state, not the delta — this is the source for what moved."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


TOOL_DEFINITIONS.extend(MEMORY_TOOL_DEFINITIONS)

# Cap the graph tool's output so a hot symbol (thousands of call sites) can't
# flood the model's context; the model can narrow the query if it needs more.
_GRAPH_MAX_LINES = 100


def _folder_names(sb, folder_ids: list[str]) -> dict[str, str]:
    """Map folder_id -> repo name for labeling cross-repo graph results."""
    if not folder_ids:
        return {}
    rows = (sb.table("folders").select("id,name").in_("id", folder_ids).execute().data) or []
    return {r["id"]: r["name"] for r in rows}


def _code_graph_lookup(
    tool_input: dict,
    scope_folder_ids: list[str] | None,
    scope_filename: str | None = None,
    *,
    user_id: str | None = None,
) -> str:
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

    def _when(row: dict) -> str:
        # File's last-(re)indexed-after-change date, so the agent can weigh recency.
        d = str(row.get("updated_at") or "")[:10]
        return f" (updated {d})" if d else ""

    lines: list[str] = []
    scoped_outline = None
    if op == "outline" and user_id is not None:
        scoped_outline = {}
        for row in graph_store.outline_scope(sb, owner_id=user_id, folder_ids=folders, path=path):
            scoped_outline.setdefault(row["folder_id"], []).append(row)
    for fid in folders:
        repo = names.get(fid, fid)
        if op == "definition":
            for r in graph_store.find_definition(sb, folder_id=fid, symbol=symbol):
                if scope_filename and r.get("file") != scope_filename:
                    continue
                lines.append(
                    f"[{repo}] {r['kind']} {r['symbol']} — {r['file']}:{r['start_line']}{_when(r)}"
                )
        elif op == "references":
            for r in graph_store.find_references(sb, folder_id=fid, symbol=symbol):
                if scope_filename and r.get("ref_file") != scope_filename:
                    continue
                lines.append(f"[{repo}] {r['relation']} at {r['ref_file']}:{r['ref_line']}")
        elif op == "impact":
            for r in graph_store.impact_of(sb, folder_id=fid, symbol=symbol):
                if scope_filename and r.get("file") != scope_filename:
                    continue
                lines.append(
                    f"[{repo}] depth {r['depth']}: {r['symbol']} — "
                    f"{r['file']}:{r['start_line']}{_when(r)}"
                )
        elif op == "outline":
            for r in (
                scoped_outline.get(fid, [])
                if scoped_outline is not None
                else graph_store.outline(sb, folder_id=fid, path=path)
            ):
                if scope_filename and r.get("file") != scope_filename:
                    continue
                lines.append(
                    f"[{repo}] {r['kind']} {r['symbol']} — {r['file']}:{r['start_line']}{_when(r)}"
                )
        else:
            return f"Unknown code_graph_lookup operation: '{op}'."

    if not lines:
        target = symbol or path
        message = f"No code-graph results for '{target}' ({op}) in the repositories in scope."
        if op in ("references", "impact"):
            suggestions = []
            for fid in folders:
                for row in graph_store.find_definition(sb, folder_id=fid, symbol=symbol, limit=5):
                    if scope_filename and row.get("file") != scope_filename:
                        continue
                    suggestions.append(
                        f"[{names.get(fid, fid)}] {row['symbol']} — "
                        f"{row['file']}:{row['start_line']}"
                    )
                    if len(suggestions) >= 8:
                        break
                if len(suggestions) >= 8:
                    break
            if suggestions:
                return (
                    message
                    + (
                        "\nRelated indexed definitions (suggestions, not confirmed references). "
                        "Retry with the full symbol shown, or search the source directly:\n"
                    )
                    + "\n".join(suggestions)
                )
        return message
    if len(lines) > _GRAPH_MAX_LINES:
        extra = len(lines) - _GRAPH_MAX_LINES
        return "\n".join(lines[:_GRAPH_MAX_LINES]) + f"\n… (+{extra} more — narrow the query)"
    return "\n".join(lines)


def _recent_changes(user_id: str, scope_folder_ids: list[str] | None) -> str:
    """Recent-work digest (commit themes + highlights) per repo in scope.

    Reads Mihari-maintained `activity` briefing section — the only source
    that captures the CHANGE DELTA (git history), which semantic search over the
    current code cannot. Fans out over the scope folders and labels by repo."""
    folders = scope_folder_ids or []
    if not folders:
        return "No repositories are in scope."
    sb = get_supabase()
    names = _folder_names(sb, folders)
    blocks: list[str] = []
    for fid in folders:
        latest = get_latest_summary(sb, fid, user_id)
        if not latest:
            continue
        from services.folder_summary.briefing_schema import snapshot_sections

        sections = snapshot_sections(latest)
        activity = sections.get("activity") or {}
        content = activity.get("content") or {}
        summary = content.get("summary")
        highlights = content.get("highlights") or []
        if not summary and not highlights:
            continue
        repo = names.get(fid, fid)
        when = str(activity.get("updated_at") or "")[:10]
        block = [f"## {repo}" + (f" (as of {when})" if when else "")]
        if summary:
            block.append(summary)
        block.extend(f"- {h}" for h in highlights)
        blocks.append("\n".join(block))
    if not blocks:
        return (
            "No recent-changes digest is available for the repositories in scope "
            "(the activity section hasn't been generated yet)."
        )
    return "\n\n".join(blocks)


@traceable(name="execute_tool", run_type="tool")
def execute_tool(
    tool_name: str,
    tool_input: dict,
    user_id: str,
    fast_mode: bool = False,
    scope_folder_ids: list[str] | None = None,
    scope_filename: str | None = None,
    debug_retrieval: list | None = None,
    citations: CitationRegistry | None = None,
    full_debug: bool = False,
) -> str:
    """Execute a tool call and return the result as a string.

    When debug_retrieval is a list, knowledge_base_search appends a structured
    record per retrieved chunk (content, source, type, rerank score, date) for
    the UI's debug inspector. Purely additive — the returned text is unchanged.

    When a CitationRegistry is passed, each retrieved chunk's header is prefixed
    with its stable [N] so the model can cite it inline, and the source is
    registered for the frontend to map N → source.
    """
    if tool_name in {"search_agent_history", "read_agent_evidence"}:
        from services.agent_memory_tools import execute_memory_tool

        return execute_memory_tool(
            get_supabase_thread_safe(),
            tool_name,
            tool_input,
            user_id,
            scope_folder_ids,
            scope_filename,
            citations,
            debug_retrieval=debug_retrieval,
        )
    if tool_name == "knowledge_base_search":
        query = tool_input["query"]
        embedding = embed_query(query)
        top_k = tool_input.get("top_k", 5)
        if type(top_k) is not int or not 1 <= top_k <= 8:
            return "Invalid knowledge-base result limit."
        results = search_documents(
            embedding,
            query_text=query,
            user_id=user_id,
            top_k=top_k,
            fast_mode=fast_mode,
            folder_ids=scope_folder_ids,
            source_filename=scope_filename,
            created_after=tool_input.get("created_after"),
            created_before=tool_input.get("created_before"),
        )
        if full_debug and results:
            sb = get_supabase()
            for table, kind in (("documents", "document"), ("code_chunks", "code")):
                selected = [
                    r for r in results if (r.get("source_type") == "code") == (kind == "code")
                ]
                ids = [r["id"] for r in selected if r.get("id")]
                if not ids:
                    for result in selected:
                        result["_outside_execution_scope"] = True
                    continue
                columns = (
                    "id,folder_id,file_hash,file"
                    if kind == "code"
                    else "id,folder_id,content_hash,source_filename"
                )
                rows = (
                    sb.table(table)
                    .select(columns)
                    .eq("user_id", user_id)
                    .in_("id", ids)
                    .execute()
                    .data
                    or []
                )
                authoritative = {str(row["id"]): row for row in rows}
                for result in selected:
                    row = authoritative.get(str(result.get("id")))
                    if row is None or row["folder_id"] not in (scope_folder_ids or []):
                        result["_outside_execution_scope"] = True
                        continue
                    actual_filename = (
                        row.get("file") if kind == "code" else row.get("source_filename")
                    )
                    if scope_filename and actual_filename != scope_filename:
                        result["_outside_execution_scope"] = True
                        continue
                    result["metadata"] = {
                        **(result.get("metadata") or {}),
                        "folder_id": row["folder_id"],
                        "source_id": str(row["id"]),
                        "revision_id": row.get("file_hash") or row.get("content_hash"),
                        "snapshot_availability": "file content hash; indexed HEAD unavailable",
                    }
            results = [r for r in results if not r.get("_outside_execution_scope")]
        if not results:
            return "No relevant documents found in the knowledge base."
        chunks = []
        batch = getattr(citations, "register_many", None) if citations is not None else None
        numbers = batch(results) if callable(batch) else None
        for index, r in enumerate(results):
            meta = r.get("metadata") or {}
            source = meta.get("source_filename", "unknown")
            if r.get("source_type") == "code":
                # Code hits are actual source, not documentation — label them so
                # the model can distinguish ground truth from narrative. The date
                # is when this file's content was last (re)indexed after a change
                # (file-level), so the agent can weigh recency.
                symbol = meta.get("code_symbol")
                updated = str(r.get("created_at") or "")[:10]
                label = f"{source} — {symbol}" if symbol else source
                body = f"Code: {label} — updated {updated}" if updated else f"Code: {label}"
            else:
                # Date in the header lets the model weigh freshness and cite
                # as-of dates — retrieval alone can't resolve conflicting facts.
                date = str(r.get("created_at") or "")[:10]
                body = f"Source: {source} — {date}" if date else f"Source: {source}"
                updated = str(r.get("last_updated") or "")[:10]
                if updated:
                    body += f" — last updated {updated}"
            # Prefix with the stable citation number [N] so the model can cite it
            # inline; without a registry, keep the original bracketed header.
            citation_number = (
                numbers[index]
                if numbers is not None
                else citations.register(r)
                if citations is not None
                else None
            )
            if citations is not None:
                header = f"[{citation_number}] {body}"
            else:
                header = f"[{body}]"
            chunks.append(f"{header}\n{r['content']}")
            if debug_retrieval is not None:
                meta = r.get("metadata") or {}
                debug_retrieval.append(
                    {
                        "query": query,
                        "source": meta.get("source_filename", "unknown"),
                        "source_type": r.get("source_type") or "document",
                        "symbol": meta.get("code_symbol"),
                        "rerank_score": r.get("rerank_score"),
                        "similarity": r.get("similarity"),
                        "date": str(r.get("created_at") or "")[:10] or None,
                        "last_updated": str(r.get("last_updated") or "")[:10] or None,
                        "content": (
                            (r.get("content") or "")
                            if full_debug
                            else (r.get("content") or "")[:1200]
                        ),
                        **(
                            {
                                "metadata": meta,
                                "source_id": r.get("id"),
                                "folder_id": meta.get("folder_id"),
                                "citation_number": citation_number,
                            }
                            if full_debug
                            else {}
                        ),
                    }
                )
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
        return _code_graph_lookup(tool_input, scope_folder_ids, scope_filename, user_id=user_id)

    if tool_name == "recent_changes":
        return _recent_changes(user_id, scope_folder_ids)

    return f"Unknown tool: {tool_name}"
