"""MCP server exposing knowledge base tools over SSE transport."""

import contextvars
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from db.client import get_supabase
from services.embeddings import embed_query
from services.evaluation import evaluate_rag_pipeline
from services.mem0_sync import MemoryCategory, get_client_for_folder
from services.mem0_sync.client import MemoryScope
from services.mem0_sync.fanout import fanout_search
from services.search import search_documents
from services.text_to_sql import generate_and_execute_sql

MCP_PORT = int(os.environ.get("MCP_PORT", "8001"))

mcp = FastMCP("Agentic RAG Knowledge Base", host="0.0.0.0", port=MCP_PORT)

# Per-request user_id via contextvars (safe for concurrent connections)
_current_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_user_id", default=None
)
_current_scope_folder_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_scope_folder_id", default=None
)


def _verify_api_key(key: str) -> tuple[str, str] | None:
    """Verify API key and return (user_id, scope_folder_id) if valid."""
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    sb = get_supabase()
    result = (
        sb.table("api_keys").select("user_id, scope_folder_id").eq("key_hash", key_hash).execute()
    )
    if result.data and result.data[0].get("scope_folder_id"):
        return result.data[0]["user_id"], result.data[0]["scope_folder_id"]
    return None


@mcp.tool()
def knowledge_base_search(query: str) -> str:
    """Search across all knowledge for this scope: documents AND any connected
    memory (Mem0) — fanned out in parallel, merged, and audited.

    Use this for any factual lookup: past decisions, code architecture,
    ingested documents, notes, learnings. If Mem0 is connected for this
    folder, eternal preferences are always prepended and episodic memories
    are searched semantically alongside documents.

    Args:
        query: The search query.
    """
    import asyncio as _asyncio  # local to avoid changing module top-level shape

    if not _current_user_id.get():
        return "Error: Not authenticated. Provide a valid API key."
    embedding = embed_query(query)
    result = _asyncio.run(fanout_search(
        get_supabase(),
        embedding=embedding,
        query_text=query,
        user_id=_current_user_id.get(),
        folder_id=_current_scope_folder_id.get(),
        limit=10,
        channel="mcp",
    ))
    if not result.hits:
        return "No relevant content found in documents or memory."

    parts = []
    for h in result.hits:
        if h.source == "docs":
            src = (h.metadata or {}).get("source_filename", "unknown")
            parts.append(f"[Document: {src}]\n{h.content}")
        elif h.source == "mem0_eternal":
            cat = (h.metadata or {}).get("category", "preference")
            parts.append(f"[Eternal preference · {cat}]\n{h.content}")
        else:  # mem0_episodic
            cat = (h.metadata or {}).get("category", "note")
            ts = (h.metadata or {}).get("created_at", "")
            parts.append(f"[Memory · {cat} · {ts}]\n{h.content}")
    return "\n\n---\n\n".join(parts)


@mcp.tool()
def save_memory(
    content: str,
    category: str,
    scope: str = "episodic",
    tags: str = "",
) -> str:
    """Save a memory to Mem0. Every write carries user_id + agent_id + category.

    Three fields are ALWAYS enforced by our proxy:
      • user_id  — resolved from your API key.
      • agent_id — set to the API key's scope folder id (memory namespace).
                   API keys with no scope folder cannot save memories.
      • category — you MUST provide one of the six values below. There is
                   no default; picking the right category is how we
                   distinguish policy from history, decisions from notes.

    Categories:
      • "decision"   — an architectural or design choice you made
      • "finding"    — an empirical fact discovered by investigation
      • "issue"      — a known bug, limitation, or workaround
      • "preference" — how the user wants to work (usually eternal)
      • "session"    — summary of what was done in a session
      • "note"       — freeform (use sparingly; prefer a specific category)

    Scopes:
      • "eternal"  — always inlined at session start (typically preferences)
      • "episodic" — recorded, retrievable via semantic search (default)

    Args:
        content: The memory to save. One sentence is ideal; two is fine.
        category: REQUIRED. One of decision/finding/issue/preference/session/note.
        scope: "eternal" for policies, "episodic" for history (default).
        tags: Comma-separated tags for filtering (e.g. "auth,security").

    Returns:
        JSON with {ok, memory_id, duplicate, scope, category, tags}.
    """
    if not _current_user_id.get():
        return json.dumps({"ok": False, "error": "Not authenticated. Provide a valid API key."})
    folder_id = _current_scope_folder_id.get()
    if not folder_id:
        return json.dumps({
            "ok": False,
            "error": "This API key has no scope folder; cannot infer agent_id.",
            "fix": "Mint an API key scoped to a folder in Settings.",
        })
    # Explicit category check — refuse (don't silently substitute 'note').
    if not category or category not in MemoryCategory.all():
        return json.dumps({
            "ok": False,
            "error": f"category is required and must be one of {list(MemoryCategory.all())}.",
            "got": category,
        })
    if scope not in (MemoryScope.ETERNAL, MemoryScope.EPISODIC):
        return json.dumps({
            "ok": False,
            "error": "scope must be 'eternal' or 'episodic'.",
            "got": scope,
        })
    if not content or not content.strip():
        return json.dumps({"ok": False, "error": "content is required."})

    client = get_client_for_folder(get_supabase(), folder_id, _current_user_id.get())
    if client is None:
        return json.dumps({
            "ok": False,
            "error": "No Mem0 integration configured for this folder.",
            "fix": "Connect Mem0 for this folder in the app's Settings page.",
        })
    tag_list = [t.strip() for t in (tags or "").split(",") if t.strip()]
    result = client.add(
        content, scope=scope, category=category, tags=tag_list, written_by="claude-code"
    )
    if not result.get("ok"):
        return json.dumps({"ok": False, "error": result.get("error") or "Mem0 write failed."})
    return json.dumps({
        "ok": True,
        "duplicate": result.get("duplicate", False),
        "existing_id": result.get("existing_id"),
        "scope": scope,
        "category": category,
        "tags": tag_list,
        "user_id": _current_user_id.get(),
        "agent_id": folder_id,
        "mem0_result": result.get("raw"),
    }, default=str)


@mcp.tool()
def search_memory(query: str, scope: str = "any", limit: int = 10) -> str:
    """Search Mem0 memory ONLY (not documents). Use knowledge_base_search
    for a unified query across docs + memory.

    Args:
        query: Natural language query.
        scope: "any" (default) | "eternal" | "episodic".
        limit: Max results (default 10).
    """
    if not _current_user_id.get():
        return "Error: Not authenticated."
    folder_id = _current_scope_folder_id.get()
    if not folder_id:
        return "Error: This API key has no scope folder."
    client = get_client_for_folder(get_supabase(), folder_id, _current_user_id.get())
    if client is None:
        return "No Mem0 integration configured for this folder."
    if scope not in (MemoryScope.ETERNAL, MemoryScope.EPISODIC):
        scope = MemoryScope.ANY
    hits = client.search(query, scope=scope, limit=limit)
    if not hits:
        return "No memories matched."
    return json.dumps(hits, default=str, indent=2)


@mcp.tool()
def query_documents_metadata(question: str) -> str:
    """Query structured metadata about uploaded documents using natural language.

    Use this for questions like 'how many documents are there',
    'what topics are covered', 'list all PDFs', etc.

    Args:
        question: Natural language question about document metadata.
    """
    if not _current_user_id.get():
        return "Error: Not authenticated. Provide a valid API key."

    result = generate_and_execute_sql(
        question, _current_user_id.get(), _current_scope_folder_id.get()
    )
    if result["error"]:
        return f"Query failed: {result['error']}"
    if not result["results"]:
        return "No results found."
    return f"SQL: {result['sql']}\nResults: {json.dumps(result['results'], default=str)}"


@mcp.tool()
def save_note(title: str, content: str) -> str:
    """Save a structured note (decision, learning, observation) to the knowledge base.

    Notes persist indefinitely and are scoped to the current domain.
    Check list_notes first to avoid duplicates.

    Args:
        title: Short summary of the note.
        content: Full note content.
    """
    if not _current_user_id.get():
        return "Error: Not authenticated."
    sb = get_supabase()
    user_id = _current_user_id.get()
    scope_id = _current_scope_folder_id.get()
    content_hash = hashlib.sha256(content.encode()).hexdigest()

    existing = (
        sb.table("notes")
        .select("id, title")
        .eq("user_id", user_id)
        .eq("root_folder_id", scope_id)
        .eq("content_hash", content_hash)
        .limit(1)
        .execute()
    )
    if existing.data:
        return f"Note already exists: '{existing.data[0]['title']}' (id: {existing.data[0]['id']})"

    result = (
        sb.table("notes")
        .insert(
            {
                "title": title,
                "content": content,
                "content_hash": content_hash,
                "root_folder_id": scope_id,
                "user_id": user_id,
            }
        )
        .execute()
    )
    return f"Note saved: '{title}' (id: {result.data[0]['id']})"


@mcp.tool()
def list_notes(query: str = "") -> str:
    """List notes in the current scope, optionally filtered by a search query.

    Args:
        query: Optional text to filter notes by title or content.
    """
    if not _current_user_id.get():
        return "Error: Not authenticated."
    sb = get_supabase()
    q = (
        sb.table("notes")
        .select("id, title, content, created_at")
        .eq("user_id", _current_user_id.get())
        .eq("root_folder_id", _current_scope_folder_id.get())
    )
    if query:
        safe_query = (
            query.replace("%", "")
            .replace(".", "")
            .replace(",", "")
            .replace("(", "")
            .replace(")", "")
        )
        q = q.or_(f"title.ilike.%{safe_query}%,content.ilike.%{safe_query}%")
    result = q.order("created_at", desc=True).execute()
    notes = result.data

    if not notes:
        return "No notes found."

    lines = []
    for n in notes:
        lines.append(
            f"- **{n['title']}** (id: {n['id']}, {n['created_at'][:10]})\n  {n['content'][:200]}"
        )
    return "\n".join(lines)


@mcp.tool()
def delete_note(note_id: str) -> str:
    """Delete a note by ID.

    Args:
        note_id: The UUID of the note to delete.
    """
    if not _current_user_id.get():
        return "Error: Not authenticated."
    sb = get_supabase()
    result = (
        sb.table("notes")
        .delete()
        .eq("id", note_id)
        .eq("user_id", _current_user_id.get())
        .eq("root_folder_id", _current_scope_folder_id.get())
        .execute()
    )
    if not result.data:
        return "Note not found or not in current scope."
    return "Note deleted."


@mcp.tool()
def set_context(key: str, value: str) -> str:
    """Set a context entry (ephemeral working memory, 7-day TTL).

    Use for current task, recent decisions, temporary state.
    Overwrites existing value for the same key.

    Args:
        key: Context key (e.g., 'current_task', 'active_branch').
        value: Context value.
    """
    if not _current_user_id.get():
        return "Error: Not authenticated."
    sb = get_supabase()
    user_id = _current_user_id.get()
    scope_id = _current_scope_folder_id.get()

    sb.table("context").upsert(
        {
            "key": key,
            "value": value,
            "root_folder_id": scope_id,
            "user_id": user_id,
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
        },
        on_conflict="user_id,root_folder_id,key",
    ).execute()

    return f"Context set: {key}"


@mcp.tool()
def get_context(key: str) -> str:
    """Get a single context value by key.

    Args:
        key: The context key to look up.
    """
    if not _current_user_id.get():
        return "Error: Not authenticated."
    sb = get_supabase()
    result = (
        sb.table("context")
        .select("value, expires_at")
        .eq("user_id", _current_user_id.get())
        .eq("root_folder_id", _current_scope_folder_id.get())
        .eq("key", key)
        .gt("expires_at", datetime.now(timezone.utc).isoformat())
        .limit(1)
        .execute()
    )
    if not result.data:
        return f"No context found for key: {key}"
    return result.data[0]["value"]


@mcp.tool()
def list_context() -> str:
    """List all active context entries in the current scope."""
    if not _current_user_id.get():
        return "Error: Not authenticated."
    sb = get_supabase()
    result = (
        sb.table("context")
        .select("id, key, value, expires_at")
        .eq("user_id", _current_user_id.get())
        .eq("root_folder_id", _current_scope_folder_id.get())
        .gt("expires_at", datetime.now(timezone.utc).isoformat())
        .order("key")
        .execute()
    )
    if not result.data:
        return "No active context entries."

    lines = []
    for c in result.data:
        lines.append(f"- **{c['key']}**: {c['value']} (expires: {c['expires_at'][:10]})")
    return "\n".join(lines)


@mcp.tool()
def clear_context(key: str = "") -> str:
    """Clear context entries. If key is provided, clear only that key. Otherwise clear all.

    Args:
        key: Optional specific key to clear. Empty string clears all context.
    """
    if not _current_user_id.get():
        return "Error: Not authenticated."
    sb = get_supabase()
    query = (
        sb.table("context")
        .delete()
        .eq("user_id", _current_user_id.get())
        .eq("root_folder_id", _current_scope_folder_id.get())
    )
    if key:
        query = query.eq("key", key)
    query.execute()
    return f"Context cleared: {'key=' + key if key else 'all'}"


@mcp.tool()
def evaluate_retrieval(questions: str) -> str:
    """Evaluate the RAG pipeline quality using RAGAS metrics.

    Runs test questions through retrieval + generation and scores with
    Faithfulness, Answer Relevancy, and Context Precision.

    Args:
        questions: Newline-separated list of test questions.
            Optionally add ground truth after a pipe: "question | ground truth"
    """
    if not _current_user_id.get():
        return "Error: Not authenticated."

    test_questions = []
    for line in questions.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            q, gt = line.split("|", 1)
            test_questions.append({"question": q.strip(), "ground_truth": gt.strip()})
        else:
            test_questions.append({"question": line})

    if not test_questions:
        return "Error: No questions provided."

    result = evaluate_rag_pipeline(
        test_questions=test_questions,
        user_id=_current_user_id.get(),
        root_folder_id=_current_scope_folder_id.get(),
    )

    # Format results
    lines = ["## RAGAS Evaluation Results\n"]
    lines.append("### Aggregate Scores")
    for metric, score in result["aggregate"].items():
        lines.append(f"- **{metric}**: {score:.3f}")

    lines.append(f"\n### Per-Question Details ({result['num_questions']} questions)")
    for detail in result["details"]:
        lines.append(f"\n**Q:** {detail['question']}")
        lines.append(f"**A:** {detail['response'][:200]}...")
        lines.append(f"**Contexts retrieved:** {detail['num_contexts']}")
        for metric, score in detail["scores"].items():
            lines.append(f"  - {metric}: {score:.3f}")

    return "\n".join(lines)


@mcp.tool()
def get_folder_orientation(folder_name: str | None = None) -> str:
    """Load a compact orientation summary of a folder for session start.

    Call this at the beginning of a session to get the big picture of what a
    folder contains before drilling into specific documents. The summary is
    regenerated nightly (delta) with a weekly full rebuild, so it stays fresh
    without burning tokens on every query.

    Args:
        folder_name: Optional folder name to look up. If omitted, uses the
            folder scoped to this API key. Case-insensitive prefix match.

    Returns:
        A JSON string containing:
        - summary: purpose, overview, themes, key_documents, key_facts, entities, gotchas
        - rules: eternal preferences from Mem0 that ALWAYS apply (empty if Mem0
                 is not connected for this folder)
        - recent_activity:
            - learnings: last N days of episodic memories (empty if no Mem0)
            - changes: files added/removed/modified in the KB since the previous summary
            - commits: recent GitHub activity (empty if no GitHub integration)
        - metadata: last_generated_at, kind (full|delta|seed), doc_count
    """
    if not _current_user_id.get():
        return "Error: Not authenticated. Provide a valid API key."

    user_id = _current_user_id.get()
    sb = get_supabase()

    # Resolve the target folder id.
    if folder_name:
        r = (
            sb.table("folders")
            .select("id, name")
            .eq("user_id", user_id)
            .ilike("name", f"{folder_name}%")
            .order("name")
            .limit(1)
            .execute()
        )
        if not r.data:
            return f"No folder found matching '{folder_name}'."
        folder_id = r.data[0]["id"]
        folder_name_resolved = r.data[0]["name"]
    else:
        folder_id = _current_scope_folder_id.get()
        if not folder_id:
            return (
                "This API key has no scope folder and no folder_name was given. "
                "Pass folder_name to select one."
            )
        r = sb.table("folders").select("name").eq("id", folder_id).limit(1).execute()
        folder_name_resolved = r.data[0]["name"] if r.data else "(scope folder)"

    # Fetch latest summary.
    latest = (
        sb.table("folder_summaries")
        .select("*")
        .eq("folder_id", folder_id)
        .eq("user_id", user_id)
        .order("generated_at", desc=True)
        .limit(1)
        .execute()
    )
    if not latest.data:
        return (
            f"No orientation summary exists yet for '{folder_name_resolved}'. "
            "The nightly cron will build one, or trigger a manual regenerate via the app."
        )

    row = latest.data[0]

    # Compose the recent_activity block. Each source is lazily-configured:
    # if there's no integration, we return an empty list, not an error.
    rules: list[dict] = []
    recent_learnings: list[dict] = []
    mem0_client = get_client_for_folder(sb, folder_id, user_id)
    if mem0_client is not None:
        try:
            for r in mem0_client.list_eternal(limit=50):
                md = r.get("metadata") or {}
                rules.append({
                    "content": r.get("memory"),
                    "category": md.get("category"),
                    "tags": md.get("tags", []),
                    "id": r.get("id"),
                })
            for r in mem0_client.list_recent_episodic(days=14, limit=20):
                md = r.get("metadata") or {}
                recent_learnings.append({
                    "content": r.get("memory"),
                    "category": md.get("category"),
                    "created_at": r.get("created_at"),
                    "tags": md.get("tags", []),
                })
        except Exception:  # noqa: BLE001 — non-fatal
            pass

    # GitHub commits: pull from documents where source_type in
    # github_commit/pr/issue and folder is in subtree, up to N recent.
    recent_commits: list[dict] = []
    try:
        gh_rows = (
            sb.table("documents").select(
                "source_filename, source_type, metadata, content, created_at"
            )
            .eq("user_id", user_id)
            .eq("root_folder_id", folder_id)
            .in_("source_type", ["github_commit", "github_pr", "github_issue"])
            .order("created_at", desc=True)
            .limit(20)
            .execute()
            .data
            or []
        )
        for g in gh_rows:
            recent_commits.append({
                "kind": g.get("source_type"),
                "ref": g.get("source_filename"),
                "title": (g.get("metadata") or {}).get("title") or (g.get("content") or "")[:120],
                "url": (g.get("metadata") or {}).get("url"),
                "created_at": g.get("created_at"),
            })
    except Exception:  # noqa: BLE001
        pass

    payload = {
        "folder": folder_name_resolved,
        "summary": row.get("content") or {},
        "rules": rules,
        "recent_activity": {
            "learnings": recent_learnings,
            "changes": row.get("changed_files") or {},
            "commits": recent_commits,
        },
        "metadata": {
            "last_generated_at": row.get("generated_at"),
            "kind": row.get("kind"),
            "doc_count": row.get("doc_count"),
            "trigger": row.get("trigger"),
            "mem0_connected": mem0_client is not None,
            "github_connected": len(recent_commits) > 0,
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


class ApiKeyAuthMiddleware:
    """Pure ASGI middleware for API key auth (SSE-compatible, no buffering)."""

    SKIP_PATHS = {"/", "/health"}

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")

        # Health endpoint
        if path == "/health":
            response = JSONResponse({"status": "ok"})
            await response(scope, receive, send)
            return

        # Skip auth for root
        if path in self.SKIP_PATHS:
            await self.app(scope, receive, send)
            return

        # Extract Authorization header
        headers = dict(scope.get("headers", []))
        auth_value = headers.get(b"authorization", b"").decode()

        if not auth_value.startswith("Bearer "):
            response = JSONResponse(
                {"error": "Missing Authorization: Bearer <api-key> header"},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        api_key = auth_value.split(" ", 1)[1]
        result = _verify_api_key(api_key)
        if not result:
            response = JSONResponse({"error": "Invalid or unscoped API key"}, status_code=401)
            await response(scope, receive, send)
            return

        user_id, scope_folder_id = result
        _current_user_id.set(user_id)
        _current_scope_folder_id.set(scope_folder_id)
        await self.app(scope, receive, send)


if __name__ == "__main__":
    print(f"Starting MCP server on port {MCP_PORT}...")
    print(f"SSE endpoint: http://localhost:{MCP_PORT}/sse")

    sse_app = mcp.sse_app()
    app = ApiKeyAuthMiddleware(sse_app)

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=MCP_PORT)
