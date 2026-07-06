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

mcp = FastMCP("Kioku Second Brain", host="0.0.0.0", port=MCP_PORT)

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


def _descendant_folder_ids(sb, root_id: str, user_id: str) -> list[str]:
    """BFS the folders tree — returns root_id + all descendants (inclusive).
    Uses the existing user_id filter at each hop so a misconfigured
    parent_id can never leak another user's folder into the traversal."""
    result = [root_id]
    frontier = [root_id]
    while frontier:
        r = (
            sb.table("folders").select("id")
            .in_("parent_id", frontier).eq("user_id", user_id).execute()
            .data or []
        )
        next_ids = [row["id"] for row in r]
        if not next_ids:
            break
        result.extend(next_ids)
        frontier = next_ids
    return result


def resolve_focus_folder(
    sb, *, scope_folder_id: str, user_id: str, focus: str | None,
) -> tuple[str, str] | tuple[None, str]:
    """Resolve an optional focus arg to (folder_id, folder_name).

    `focus` accepts three forms:
      - None → the scope folder itself.
      - A UUID → looked up directly; must be scope or a descendant.
      - A plain name like 'c360-lead' or slash-path like 'cosm/c360-lead'
        → BFS the subtree, case-insensitive match on the leaf name (or
        the whole path when '/' is present).

    Returns:
      (folder_id, folder_name) on success, or
      (None, error_message) on failure.

    All lookups are restricted to descendants of scope_folder_id so a
    root-scoped key can drill down but cannot escape its scope.
    """
    if not scope_folder_id:
        return (None, "This API key has no folder scope.")

    subtree_ids = _descendant_folder_ids(sb, scope_folder_id, user_id)
    if not focus:
        row = (
            sb.table("folders").select("id, name")
            .eq("id", scope_folder_id).eq("user_id", user_id)
            .limit(1).execute().data
        )
        if not row:
            return (None, "Scope folder not found.")
        return (row[0]["id"], row[0]["name"])

    focus = focus.strip()
    # UUID form?
    if len(focus) == 36 and focus.count("-") == 4:
        if focus not in subtree_ids:
            return (None, f"Folder {focus!r} is not inside your scope.")
        row = (
            sb.table("folders").select("id, name")
            .eq("id", focus).eq("user_id", user_id).limit(1).execute().data
        )
        if not row:
            return (None, f"Folder {focus!r} not found.")
        return (row[0]["id"], row[0]["name"])

    # Path form ('cosm/c360-lead' or 'c360-lead')
    parts = [p for p in focus.split("/") if p]
    if not parts:
        return (None, "Empty focus argument.")
    target_name = parts[-1].lower()

    # Load candidate rows in the subtree with matching name.
    rows = (
        sb.table("folders").select("id, name, parent_id")
        .in_("id", subtree_ids).eq("user_id", user_id)
        .ilike("name", target_name).execute()
        .data or []
    )
    # Case-insensitive strict match on the leaf name
    exact = [r for r in rows if r["name"].lower() == target_name]
    if not exact:
        return (None, f"No folder named {target_name!r} in your scope.")

    # If multiple, prefer the one whose path matches all provided parts.
    if len(exact) == 1:
        return (exact[0]["id"], exact[0]["name"])

    if len(parts) > 1:
        # Walk each candidate's ancestry, compare against parts[:-1]
        def ancestry_names(fid: str) -> list[str]:
            names: list[str] = []
            cur = fid
            for _ in range(30):
                rr = (
                    sb.table("folders").select("name, parent_id")
                    .eq("id", cur).eq("user_id", user_id).limit(1).execute()
                    .data
                )
                if not rr:
                    break
                names.append(rr[0]["name"])
                if not rr[0].get("parent_id"):
                    break
                cur = rr[0]["parent_id"]
            return list(reversed(names))
        matches = []
        wanted = [p.lower() for p in parts]
        for cand in exact:
            path = [n.lower() for n in ancestry_names(cand["id"])]
            if path[-len(wanted):] == wanted:
                matches.append(cand)
        if len(matches) == 1:
            return (matches[0]["id"], matches[0]["name"])
        elif not matches:
            return (
                None,
                f"No folder path {focus!r} matches your scope subtree.",
            )
        else:
            return (
                None,
                f"Ambiguous focus {focus!r} — matches {len(matches)} folders. "
                f"Try a longer path.",
            )
    return (
        None,
        f"Ambiguous focus {focus!r} — {len(exact)} folders match. "
        "Try a slash-path like 'parent/child'.",
    )


def _folder_tree_under_scope(
    sb, *, scope_folder_id: str, user_id: str,
) -> list[dict]:
    """List all folders under scope with {id, name, kind, path, has_briefing}.

    Handy for a coding agent's list_folders_in_scope tool — shows the
    whole subtree so the agent knows what to focus on.
    """
    subtree_ids = _descendant_folder_ids(sb, scope_folder_id, user_id)
    if not subtree_ids:
        return []
    rows = (
        sb.table("folders").select("id, name, parent_id, kind")
        .in_("id", subtree_ids).eq("user_id", user_id).execute()
        .data or []
    )
    by_id = {r["id"]: r for r in rows}

    def build_path(fid: str) -> str:
        parts: list[str] = []
        cur = fid
        for _ in range(30):
            if cur not in by_id:
                break
            parts.append(by_id[cur]["name"])
            parent = by_id[cur].get("parent_id")
            if not parent or parent not in by_id:
                break
            cur = parent
        return "/".join(reversed(parts))

    # Which folders have a briefing/summary row?
    with_summaries = (
        sb.table("folder_summaries").select("folder_id")
        .in_("folder_id", subtree_ids).eq("user_id", user_id).execute()
        .data or []
    )
    summarized = {r["folder_id"] for r in with_summaries}

    return sorted(
        [
            {
                "id": r["id"],
                "name": r["name"],
                "kind": r.get("kind") or "folder",
                "path": build_path(r["id"]),
                "has_summary": r["id"] in summarized,
            }
            for r in rows
        ],
        key=lambda x: x["path"],
    )


@mcp.tool()
async def knowledge_base_search(query: str) -> str:
    """Search across all knowledge for this scope: documents AND any connected
    memory (Mem0) — fanned out in parallel, merged, and audited.

    Use this for any factual lookup: past decisions, code architecture,
    ingested documents, notes, learnings. If Mem0 is connected for this
    folder, eternal preferences are always prepended and episodic memories
    are searched semantically alongside documents.

    Args:
        query: The search query.
    """
    if not _current_user_id.get():
        return "Error: Not authenticated. Provide a valid API key."
    # Tool is async so FastMCP's own event loop drives fanout_search directly
    # (previously we tried asyncio.run which nested loops and crashed).
    embedding = embed_query(query)
    result = await fanout_search(
        get_supabase(),
        embedding=embedding,
        query_text=query,
        user_id=_current_user_id.get(),
        folder_id=_current_scope_folder_id.get(),
        limit=10,
        channel="mcp",
    )
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
def list_folders_in_scope() -> str:
    """Discover the folder subtree accessible to this API key.

    Returns every folder under the key's scope with its name, kind
    ('folder' or 'repo'), full slash-path (like 'cosm/c360-lead'),
    and whether it already has a summary/briefing.

    Common flow: when starting a session with a root-scoped key,
    call this first to see the workspace layout, then focus on a
    specific repo with get_folder_briefing(folder='<name>').
    """
    if not _current_user_id.get():
        return "Error: Not authenticated."
    scope = _current_scope_folder_id.get()
    if not scope:
        return "Error: This API key has no folder scope."
    sb = get_supabase()
    tree = _folder_tree_under_scope(
        sb, scope_folder_id=scope, user_id=_current_user_id.get(),
    )
    return json.dumps({
        "scope_folder_id": scope,
        "folders": tree,
        "hint": (
            "Call get_folder_briefing(folder='<name>') or "
            "get_folder_orientation(folder='<name>') to focus on any of these. "
            "The 'folder' argument accepts a name ('c360-lead'), a slash-path "
            "('cosm/c360-lead'), or a UUID. Repo folders have the strict "
            "8-section briefing; regular folders have a freeform summary."
        ),
    }, indent=2, ensure_ascii=False)


@mcp.tool()
def get_folder_briefing_schema() -> str:
    """Return the canonical shape of a folder briefing.

    Call once at session start (or when you need to write to a section)
    to learn every section name, its expected content shape, and short
    notes on how to author it. Use with update_folder_briefing_section
    when you learn something the user hasn't captured yet.
    """
    from services.folder_summary.briefing import (
        BRIEFING_SCHEMA_VERSION, SECTION_KEYS,
    )
    schema = {
        "version": BRIEFING_SCHEMA_VERSION,
        "sections": SECTION_KEYS,
        "notes": {
            "overview": "One sentence purpose + 2-4 sentence description.",
            "architecture": (
                "How the system fits together. summary (str), components "
                "(list of {name, role, path}), data_flow (str)."
            ),
            "preferences": "Verbatim rules. Prefer using save_memory + regen over editing directly.",
            "important_files": "3-8 files an agent would open first. list of {path, role, why}.",
            "how_it_runs": "Requirements list + local_dev setup string.",
            "deployment": "Environments list, how_to_deploy, ci_cd_notes.",
            "dependencies": "Auto-populated from manifests. Prefer regen over editing.",
            "activity": "Auto-populated from GitHub sync + Mem0. Do NOT pin — it goes stale.",
        },
    }
    return json.dumps(schema, indent=2, ensure_ascii=False)


@mcp.tool()
def get_folder_briefing(folder: str | None = None) -> str:
    """Read the briefing for a repo folder inside your scope.

    Args:
        folder: Optional focus. If omitted, uses the API key's scope
            folder. Otherwise the focus is resolved as: a plain name
            like 'c360-lead', a slash-path like 'cosm/c360-lead', or
            a UUID. Focus must be a descendant of your scope — you
            can drill INTO your subtree but cannot escape it.

    Common flow with a root-scoped key:
        # Discover the subtree
        list_folders_in_scope()
        # Focus on the repo you're working in
        get_folder_briefing(folder='c360-lead')

    Returns the full 8-section briefing (status, content, provenance,
    updated_at, updated_by per section) plus a hint reminding you to
    call update_folder_briefing_section to write back new facts.

    Non-repo folders return a helpful error — use get_folder_orientation
    for those instead.
    """
    if not _current_user_id.get():
        return "Error: Not authenticated. Provide a valid API key."
    if not _current_scope_folder_id.get():
        return "Error: No folder scope on this API key."
    from services.folder_summary.briefing import empty_briefing
    from services.folder_summary.repo import (
        get_folder, get_latest_summary,
    )
    sb = get_supabase()
    user_id = _current_user_id.get()
    resolved_id, resolved_name = resolve_focus_folder(
        sb, scope_folder_id=_current_scope_folder_id.get(),
        user_id=user_id, focus=folder,
    )
    if not resolved_id:
        return f"Error: {resolved_name}"
    folder_row = get_folder(sb, resolved_id, user_id)
    if not folder_row:
        return "Error: Folder not found."
    if (folder_row.get("kind") or "folder") != "repo":
        return (
            f"'{resolved_name}' is not a repo. Briefings are only available "
            "for GitHub-synced folders. Use get_folder_orientation for a "
            "generic summary instead."
        )
    latest = get_latest_summary(sb, resolved_id, user_id)
    sections = None
    if latest:
        sections = latest.get("sections") or (
            (latest.get("content") or {}).get("sections")
        )
    payload = {
        "folder": folder_row.get("name"),
        "sections": sections or empty_briefing(),
        "last_generated_at": (latest or {}).get("generated_at"),
        "hint": (
            "This briefing is your session-start context. If you learn "
            "something the user hasn't captured (a deployment gotcha, a "
            "'why this file matters' fact, a run-command they use), call "
            "update_folder_briefing_section(section, content, pin=True, "
            "folder=...) to save it. It survives across sessions and PC "
            "switches."
        ),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


@mcp.tool()
def replace_folder_briefing(
    sections: str,
    pin_all: bool = True,
    folder: str | None = None,
) -> str:
    """Replace the ENTIRE briefing in one call — all 8 sections at once.

    Use when you want to overwrite the whole briefing (e.g. after doing
    a big investigation that touched every area). Call
    get_folder_briefing_schema first to see the shape.

    Args:
        sections: JSON string with a top-level object where each key is
            one of the 8 section names and each value is that section's
            content shape. Partial replaces are allowed — missing keys
            are left alone and merge with the existing briefing.
        pin_all: If True (default), every provided section is marked
            pinned so auto-regen won't overwrite the changes. Set False
            for 'suggestion' behavior.
        folder: Same resolver as get_folder_briefing (name / slash-path /
            UUID). Omit to target the API key's scope folder.

    Records provenance='agent_mcp' on every provided section.
    """
    if not _current_user_id.get():
        return "Error: Not authenticated."
    from services.folder_summary.briefing import (
        BRIEFING_SCHEMA_VERSION, SECTION_KEYS, empty_briefing, new_section,
    )
    from services.folder_summary.repo import (
        get_folder, get_latest_summary,
    )
    sb = get_supabase()
    user_id = _current_user_id.get()
    resolved_id, resolved_name = resolve_focus_folder(
        sb, scope_folder_id=_current_scope_folder_id.get(),
        user_id=user_id, focus=folder,
    )
    if not resolved_id:
        return f"Error: {resolved_name}"
    folder_row = get_folder(sb, resolved_id, user_id)
    if not folder_row or (folder_row.get("kind") or "folder") != "repo":
        return f"Error: '{resolved_name}' is not a repo folder."

    try:
        payload_sections = json.loads(sections)
    except Exception as exc:  # noqa: BLE001
        return f"Error: sections argument must be valid JSON: {exc}"
    if not isinstance(payload_sections, dict):
        return "Error: sections must be a JSON object mapping section names to content."

    unknown = [k for k in payload_sections.keys() if k not in SECTION_KEYS]
    if unknown:
        return (
            f"Error: unknown section names: {unknown}. "
            f"Valid: {SECTION_KEYS}. "
            "Call get_folder_briefing_schema for shape hints."
        )

    latest = get_latest_summary(sb, resolved_id, user_id)
    current = (
        (latest or {}).get("sections")
        or ((latest or {}).get("content") or {}).get("sections")
        or empty_briefing()
    )
    for key, content in payload_sections.items():
        current[key] = new_section(
            content,
            status="pinned" if pin_all else "auto",
            provenance="agent_mcp",
            updated_by="agent_mcp",
        )
    # Reuse the same downgrade-safe insert pipeline the section update
    # tool uses so pre-migration DBs still land the row.
    payload = {
        "folder_id": resolved_id,
        "user_id": user_id,
        "kind": "briefing",
        "trigger": "mcp_edit",
        "content": {"__briefing_v": BRIEFING_SCHEMA_VERSION, "sections": current},
        "previous_content": None,
        "included_hashes": [],
        "doc_count": 0,
        "changed_files": {},
        "input_tokens": 0,
        "output_tokens": 0,
        "duration_ms": 0,
        "briefing_schema_version": BRIEFING_SCHEMA_VERSION,
        "sections": current,
    }
    last_err = None
    for _ in range(4):
        try:
            sb.table("folder_summaries").insert(payload).execute()
            return json.dumps({
                "ok": True,
                "replaced": list(payload_sections.keys()),
                "total_sections": len(current),
            }, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            msg = str(exc)
            downgraded = False
            if "kind_check" in msg and payload.get("kind") != "full":
                payload["kind"] = "full"
                downgraded = True
            if "trigger_check" in msg and payload.get("trigger") != "manual":
                payload["trigger"] = "manual"
                downgraded = True
            if ("briefing_schema_version" in msg or "sections" in msg) \
                    and "briefing_schema_version" in payload:
                payload.pop("briefing_schema_version", None)
                payload.pop("sections", None)
                downgraded = True
            if not downgraded:
                break
    return f"Error persisting briefing: {str(last_err)[:200]}"


@mcp.tool()
def update_folder_briefing_section(
    section: str,
    content: str,
    pin: bool = True,
    folder: str | None = None,
) -> str:
    """Patch one section of a repo's briefing.

    Args:
        section: One of 'overview', 'architecture', 'preferences',
            'important_files', 'how_it_runs', 'deployment',
            'dependencies', 'activity'.
        content: JSON string matching the section's shape (see
            get_folder_briefing_schema). String content is also accepted
            and stored verbatim for prose sections.
        pin: If True (default), the section is marked pinned — auto-regen
            will NOT overwrite it. Set False for 'suggestion' behavior
            where the next regen re-drafts the section.
        folder: Which repo to update. Same resolver as get_folder_briefing
            (name / slash-path / UUID). Omit to target the scope folder.

    Records provenance='agent_mcp' so the UI can attribute the edit.
    """
    if not _current_user_id.get():
        return "Error: Not authenticated."
    from services.folder_summary.briefing import (
        BRIEFING_SCHEMA_VERSION, SECTION_KEYS, new_section, empty_briefing,
    )
    from services.folder_summary.repo import (
        get_folder, get_latest_summary,
    )
    if section not in SECTION_KEYS:
        return f"Error: Unknown section '{section}'. Valid: {SECTION_KEYS}"
    sb = get_supabase()
    user_id = _current_user_id.get()
    resolved_id, resolved_name = resolve_focus_folder(
        sb, scope_folder_id=_current_scope_folder_id.get(),
        user_id=user_id, focus=folder,
    )
    if not resolved_id:
        return f"Error: {resolved_name}"
    folder_id = resolved_id
    folder_row = get_folder(sb, folder_id, user_id)
    if not folder_row or (folder_row.get("kind") or "folder") != "repo":
        return f"Error: '{resolved_name}' is not a repo folder."
    # Content may be JSON or a plain string — try JSON first, fall back
    # to raw string.
    try:
        parsed_content = json.loads(content)
    except Exception:  # noqa: BLE001
        parsed_content = content

    latest = get_latest_summary(sb, folder_id, user_id)
    sections = (
        (latest or {}).get("sections")
        or ((latest or {}).get("content") or {}).get("sections")
        or empty_briefing()
    )
    sections[section] = new_section(
        parsed_content,
        status="pinned" if pin else "auto",
        provenance="agent_mcp",
        updated_by=f"api_key_id_placeholder",  # TODO: thread real id through the middleware
    )
    payload = {
        "folder_id": folder_id,
        "user_id": user_id,
        "kind": "briefing",
        "trigger": "mcp_edit",
        "content": {"__briefing_v": BRIEFING_SCHEMA_VERSION, "sections": sections},
        "previous_content": None,
        "included_hashes": [],
        "doc_count": 0,
        "changed_files": {},
        "input_tokens": 0,
        "output_tokens": 0,
        "duration_ms": 0,
        "briefing_schema_version": BRIEFING_SCHEMA_VERSION,
        "sections": sections,
    }
    # Migration-safe downgrade chain — matches routes/briefing.py.
    last_err = None
    for _ in range(4):
        try:
            sb.table("folder_summaries").insert(payload).execute()
            return f"Updated section '{section}' (status={'pinned' if pin else 'auto'})."
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            msg = str(exc)
            downgraded = False
            if "kind_check" in msg and payload.get("kind") != "full":
                payload["kind"] = "full"
                downgraded = True
            if "trigger_check" in msg and payload.get("trigger") != "manual":
                payload["trigger"] = "manual"
                downgraded = True
            if ("briefing_schema_version" in msg or "sections" in msg) \
                    and "briefing_schema_version" in payload:
                payload.pop("briefing_schema_version", None)
                payload.pop("sections", None)
                downgraded = True
            if not downgraded:
                break
    return f"Error persisting briefing: {str(last_err)[:200]}"


@mcp.tool()
def get_folder_orientation(
    folder: str | None = None,
    folder_name: str | None = None,
) -> str:
    """Load a compact orientation summary of a folder for session start.

    Call this at the beginning of a session to get the big picture of what a
    folder contains before drilling into specific documents. The summary is
    regenerated nightly (delta) with a weekly full rebuild, so it stays fresh
    without burning tokens on every query.

    Args:
        folder: Which folder inside your scope to load. Accepts a plain
            name ('c360-lead'), a slash-path ('cosm/c360-lead'), or a
            UUID. Omit to load the scope folder itself.
        folder_name: Legacy alias for `folder`. Prefer `folder`.

    Common pattern with a root-scoped key on a workspace like 'cosm':
        # Get the workspace briefing + a subfolders index
        get_folder_orientation()
        # Focus on the repo you're actually working in
        get_folder_orientation(folder='c360-lead')

    Returns:
        A JSON string containing:
        - summary: purpose, overview, themes, key_documents, key_facts, entities, gotchas
        - rules: eternal preferences from Mem0 that ALWAYS apply (empty if Mem0
                 is not connected for this folder)
        - recent_activity:
            - learnings: last N days of episodic memories (empty if no Mem0)
            - changes: files added/removed/modified in the KB since the previous summary
            - commits: recent GitHub activity (empty if no GitHub integration)
        - subfolders: (workspace_rollup folders only) structured index of children
        - briefing: (repo folders only) the 8-section briefing
        - metadata: last_generated_at, kind, doc_count
    """
    if not _current_user_id.get():
        return "Error: Not authenticated. Provide a valid API key."

    user_id = _current_user_id.get()
    sb = get_supabase()

    # Resolver: accepts either the new `folder` arg or the legacy `folder_name`.
    focus = folder or folder_name
    folder_id, folder_name_resolved = resolve_focus_folder(
        sb, scope_folder_id=_current_scope_folder_id.get(),
        user_id=user_id, focus=focus,
    )
    if not folder_id:
        return f"Error: {folder_name_resolved}"

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
            # Read actual config presence, not doc count — a folder can be
            # connected but have no fresh commits (static repos).
            "github_connected": bool(
                sb.table("github_sync_configs").select("id")
                .eq("root_folder_id", folder_id).eq("user_id", user_id)
                .limit(1).execute().data
            ),
        },
    }

    # If this is a workspace rollup (container folder), attach the
    # structured subfolders[] index so the agent can drill into any child
    # without another orientation call. The 'summary' block still carries
    # the synthesized workspace briefing.
    if row.get("kind") == "workspace_rollup":
        try:
            from services.folder_summary.rollup import (
                build_workspace_orientation_payload,
            )
            extra = build_workspace_orientation_payload(
                sb, folder_id=folder_id, user_id=user_id, latest_row=row,
            )
            payload["subfolders"] = extra["subfolders"]
        except Exception:  # noqa: BLE001
            pass  # Don't fail orientation on rollup-index assembly errors.

    # For repo folders, add the strict 8-section briefing so a coding
    # agent has structured facts to work with immediately + can update
    # any section via update_folder_briefing_section.
    sections = row.get("sections") or (row.get("content") or {}).get("sections")
    # Detect briefing rows by shape rather than kind — the constraint may
    # not have been widened yet, in which case briefings are persisted
    # with kind='full' + sections still populated.
    is_briefing_row = (
        row.get("kind") == "briefing"
        or row.get("briefing_schema_version")
        or (isinstance(sections, dict) and any(
            k in sections for k in ("overview", "architecture", "activity")
        ))
    )
    if is_briefing_row and sections:
        payload["briefing"] = {
            "schema_version": row.get("briefing_schema_version") or 1,
            "sections": sections,
            "hint": (
                "You have write access to this briefing. If you learn "
                "something the user hasn't captured yet, call "
                "update_folder_briefing_section(section, content, pin=True) "
                "to save it. Sections persist across sessions and PC switches."
            ),
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


def _startup_healthcheck() -> None:
    """Quick synchronous ping of the dependencies the tools need. Prints
    a green/yellow line per dependency so operators see connection health
    at a glance instead of discovering it via a 500 mid-request.

    Failures are non-fatal — the server still starts, so users can
    diagnose via /health and the printed hints."""
    print()
    print("Health check:")

    # Supabase
    try:
        sb = get_supabase()
        r = sb.table("folders").select("id", head=True, count="exact").limit(1).execute()
        print(f"  ✓ Supabase       {r.count or 0} folders visible")
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ Supabase       {str(exc)[:120]}")
        print(f"    Hint: check SUPABASE_URL + SUPABASE_SERVICE_KEY in .env")

    # Anthropic
    try:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("  ✗ Anthropic      ANTHROPIC_API_KEY not set")
        else:
            print(f"  ✓ Anthropic      api key present ({os.environ['ANTHROPIC_API_KEY'][:8]}…)")
    except Exception as exc:  # noqa: BLE001
        print(f"  ✗ Anthropic      {str(exc)[:120]}")

    # Voyage (embeddings)
    if not os.environ.get("VOYAGE_API_KEY"):
        print("  ! Voyage         VOYAGE_API_KEY not set — search will fail")
    else:
        print(f"  ✓ Voyage         api key present ({os.environ['VOYAGE_API_KEY'][:8]}…)")

    print()


if __name__ == "__main__":
    print(f"Starting MCP server on port {MCP_PORT}...")
    print(f"SSE endpoint: http://localhost:{MCP_PORT}/sse")
    _startup_healthcheck()

    sse_app = mcp.sse_app()
    app = ApiKeyAuthMiddleware(sse_app)

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=MCP_PORT)
