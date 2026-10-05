"""Agentic RAG pipeline: tool-use loop with streaming."""

import json
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor

from langsmith import traceable

from db.client import get_supabase
from services.llm import Task, complete, stream_complete
from services.metrics import collect_request, record, submit_with_context
from services.timing import request, stage
from services.tools import TOOL_DEFINITIONS, execute_tool

SYSTEM_PROMPT = """You are an agentic research assistant for the user's second brain: their \
uploaded documents plus their indexed code repositories. Reason before you answer — investigate, \
cross-check, and verify. Do NOT answer from the first thing you retrieve.

## Tools
- knowledge_base_search — hybrid vector + keyword search over the user's documents AND their \
indexed source code (real code chunks, not just prose). It performs internal query expansion, so \
pass ONE clear question per call — but you may call it several times across rounds: if results are \
weak, off-target, or thin, reformulate and search again.
- code_graph_lookup — exact structural lookups in the code graph across every repo in scope: where \
a symbol is defined, who references/calls it, its blast radius (impact), or an outline of a \
file/directory. Use it for precise "where is X defined / who calls X / what depends on X" \
questions about named functions, classes, or methods.
- query_documents_metadata — structured questions about the document collection (counts, types, \
topics, dates).
- recent_changes — a digest of what changed recently across the repos in scope (commit themes + \
highlights with PR numbers, from git history). Use it for "what changed / what's new / recent \
work" questions — semantic search shows the CURRENT state, not the delta.
- web_search — only when the answer is not in the user's knowledge base or code.

## How to work (agentic)
- PLAN: decide what you need and where it lives (docs? code? code graph? web?) before acting.
- ACT & OBSERVE: retrieve, then actually read what came back. You may use multiple tools and \
search multiple times across rounds — iterate until you have enough. Do not stop at the first hit.
- EVALUATE: after retrieving, judge whether the results are relevant, complete, consistent, and \
current. If they are thin, conflicting, or stale, dig further — reformulate, switch tools, or go \
read the actual code.
- VERIFY before you answer. Do not emit a claim you have not grounded in what you retrieved.

## Code is ground truth
Documentation and design notes can be out of date; the indexed code is the current reality. For \
"how does X work / is this still true" questions, verify prose against the actual code — \
knowledge_base_search for the implementation, code_graph_lookup for structure. If a document \
conflicts with the code, trust the code and note that the doc appears outdated. For "what changed \
recently / what's new" questions, use recent_changes (git-derived) — the code shows current state, \
not the delta.

## Temporal awareness
Retrieved results carry a date in the header. For documents it is the source/edit date. For code \
and code_graph_lookup results the "updated <date>" is when that file's content was last indexed \
after a change (file-level) — a recency hint, not the authoring date. Use it: when two results \
conflict, prefer the more recently updated one and note the older differs; be wary of notably old \
code when the question is about current behavior. For time-sensitive answers state the as-of date; \
if the only support is old, say so. When the user asks about a specific period ('last month', \
'since March'), pass created_after / created_before to knowledge_base_search.

## Answering
Ground every claim in what you retrieved and cite sources — file:line for code, source name + date \
for documents. If after honest effort the knowledge base does not cover it, say so plainly rather \
than guessing."""

# Plain (non-agentic) RAG: one retrieval, then answer. No tool loop, no code
# graph / recent-changes / web, no extended thinking — the classic path.
PLAIN_PROMPT = """You are a helpful assistant answering from the user's knowledge base.

Call knowledge_base_search once with the user's question, then answer using the retrieved content. \
Cite your sources — file:line for code, source name + date for documents. If the retrieved content \
does not answer the question, say so plainly; do not guess or rely on outside knowledge."""

# Extended-thinking budget for deep-mode turns. < max_tokens so thinking and the
# answer share the ceiling.
_DEEP_THINKING_BUDGET = 2048


def _agent_params(model: str, mode: str) -> tuple[Task, int, int | None]:
    """(task, max_tokens, thinking_budget) — model picks the route, mode picks
    thinking. Only 'deep' enables extended thinking."""
    task = Task.RAG_AGENT_SONNET if model == "sonnet" else Task.RAG_AGENT
    if mode == "deep":
        return task, 8192, _DEEP_THINKING_BUDGET
    return task, 4096, None


def _mode_config(mode: str) -> tuple[str, list[dict]]:
    """(system_prompt, tools) for a mode.

    plain            → classic RAG: minimal prompt, knowledge_base_search only.
    agentic / deep   → the agentic prompt + all tools (loop, code graph, etc).
    """
    if mode == "plain":
        kb_only = [t for t in TOOL_DEFINITIONS if t["name"] == "knowledge_base_search"]
        return PLAIN_PROMPT, kb_only
    return SYSTEM_PROMPT, TOOL_DEFINITIONS


@traceable(name="answer_question", run_type="chain")
def answer_question(
    user_message: str,
    user_id: str,
    topic: str | None = None,
    keyword: str | None = None,
    model: str = "sonnet",
    mode: str = "deep",
    history: list[dict] | None = None,
    scope_folder_ids: list[str] | None = None,
    scope_filename: str | None = None,
) -> dict:
    """Run the agent loop end-to-end, return final answer + retrieved chunks.

    This is the SHARED core used by both stream_rag_response (SSE wrapper with
    DB side effects) and the eval harness (no SSE, no DB writes). When you
    change agent behavior, both paths change together — the eval can never
    drift from prod.

    Returns:
        {
            "response": str,                 # final assembled assistant text
            "retrieved_chunks": list[str],   # raw chunks the agent received
                                             # from knowledge_base_search tool
                                             # results (one entry per chunk)
            "rounds_used": int,              # how many agent loop rounds ran
            "tool_calls": int,               # total tool invocations
        }
    """
    messages = list(history or []) + [{"role": "user", "content": user_message}]

    full_response = ""
    retrieved_chunks: list[str] = []
    max_rounds = 10
    tool_call_count = 0
    rounds_used = 0
    task, max_tokens, thinking_budget = _agent_params(model, mode)
    system_prompt, tools = _mode_config(mode)

    for round_num in range(max_rounds):
        rounds_used = round_num + 1
        with stage(f"round {round_num + 1}: anthropic call"):
            response = complete(
                task=task,
                max_tokens=max_tokens,
                thinking_budget=thinking_budget,
                system=system_prompt,
                messages=messages,
                tools=tools,
            )

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            tool_call_count += len(tool_uses)

            def _run_tool(block, _indent: int = 1) -> dict:
                with stage(f"tool: {block.name}", indent=_indent):
                    result_text = execute_tool(
                        block.name,
                        block.input,
                        user_id,
                        topic,
                        keyword,
                        fast_mode=False,
                        scope_folder_ids=scope_folder_ids,
                        scope_filename=scope_filename,
                    )
                return {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                    "_tool_name": block.name,
                }

            if len(tool_uses) > 1:
                # Claude's parallel tool use: run them concurrently instead of
                # blocking on each in sequence.
                with stage(f"{len(tool_uses)} tools (parallel)"):
                    with ThreadPoolExecutor(max_workers=len(tool_uses)) as pool:
                        futures = [submit_with_context(pool, _run_tool, b, 2) for b in tool_uses]
                        tool_results = [f.result() for f in futures]
            else:
                tool_results = [_run_tool(b) for b in tool_uses]

            # Capture knowledge_base_search chunks for eval / RAGAS context metrics
            for tr in tool_results:
                if tr.get("_tool_name") == "knowledge_base_search":
                    content = tr.get("content", "")
                    if isinstance(content, str) and content:
                        chunks = [c.strip() for c in content.split("\n\n---\n\n") if c.strip()]
                        retrieved_chunks.extend(chunks)

            # Strip internal key before appending to messages (Anthropic API
            # doesn't accept unknown fields in tool_result blocks).
            api_tool_results = [
                {k: v for k, v in tr.items() if k != "_tool_name"} for tr in tool_results
            ]
            messages.append({"role": "user", "content": api_tool_results})

            continue

        # Claude is done with tools — collect the final text response
        for block in response.content:
            if hasattr(block, "text"):
                full_response += block.text
        break
    else:
        full_response = "I was unable to complete the request after multiple attempts."

    record("agent_loop", n_rounds=rounds_used, n_tool_calls=tool_call_count)

    return {
        "response": full_response,
        "retrieved_chunks": retrieved_chunks,
        "rounds_used": rounds_used,
        "tool_calls": tool_call_count,
    }


@traceable(name="stream_rag_response", run_type="chain")
def stream_rag_response(
    conversation_id: str,
    user_message: str,
    user_id: str,
    topic: str | None = None,
    keyword: str | None = None,
    model: str = "sonnet",
    mode: str = "deep",
    debug: bool = False,
    scope_folder_id: str | None = None,
    scope_filename: str | None = None,
) -> Generator[str, None, None]:
    """Agentic RAG pipeline: save message, run tool-use loop, stream response."""
    sb = get_supabase()

    # Resolve a folder scope to its subtree once — the agent may call the
    # search tool several times per turn.
    scope_folder_ids: list[str] | None = None
    if scope_folder_id:
        from services.scope import descendant_folder_ids

        scope_folder_ids = descendant_folder_ids(sb, scope_folder_id, user_id)

    _label = f"{model}/{mode}"
    with collect_request(f"rag chat turn ({_label})"):
        with request(f"rag chat turn ({_label})"):
            # 1. Save user message + update title + fetch history
            with stage("db: save user msg + fetch history"):
                sb.table("messages").insert(
                    {
                        "conversation_id": conversation_id,
                        "role": "user",
                        "content": user_message,
                    }
                ).execute()
                # Only auto-set the title if the conversation still has its
                # default null/placeholder title. Otherwise a user rename (via
                # PATCH /api/conversations/{id}) would be overwritten by every
                # subsequent user message. 'New conversation' is the DB default.
                current_title = (
                    sb.table("conversations")
                    .select("title")
                    .eq("id", conversation_id)
                    .eq("user_id", user_id)
                    .limit(1)
                    .execute()
                    .data
                )
                _title = (current_title[0].get("title") or "") if current_title else ""
                if _title in ("", "New conversation"):
                    sb.table("conversations").update({"title": user_message[:50]}).eq(
                        "id", conversation_id
                    ).eq("user_id", user_id).execute()
                history = (
                    sb.table("messages")
                    .select("role, content")
                    .eq("conversation_id", conversation_id)
                    .order("created_at")
                    .execute()
                )
                # Exclude the user message we just inserted — answer_question
                # appends user_message itself so we only pass prior history.
                prior_messages = [
                    {"role": m["role"], "content": m["content"]} for m in history.data
                ]
                # The last entry is the user message we just saved; drop it so
                # answer_question can append it cleanly.
                if prior_messages and prior_messages[-1] == {
                    "role": "user",
                    "content": user_message,
                }:
                    prior_messages = prior_messages[:-1]

            # 2. Run the tool-use loop, then stream the FINAL assistant text
            # from Anthropic as it generates. Previously we blocked on
            # answer_question and emitted the whole reply as a single 'token'
            # event, giving fake streaming with ~10s first-token latency.
            full_response = ""
            gen_started = False
            completed_cleanly = False
            debug_payload: dict | None = None
            try:
                for chunk_kind, payload in _run_loop_and_stream_final(
                    user_message=user_message,
                    user_id=user_id,
                    topic=topic,
                    keyword=keyword,
                    model=model,
                    mode=mode,
                    debug=debug,
                    history=prior_messages,
                    scope_folder_ids=scope_folder_ids,
                    scope_filename=scope_filename,
                ):
                    if chunk_kind == "stage":
                        # Loop-driven progress: 'thinking' (reasoning) or
                        # 'searching' (tool round). Emit on EVERY round, even
                        # after the model streamed a preamble — otherwise the
                        # agent going quiet for more tool rounds (which can take
                        # ~20s) looks frozen. The frontend clears the indicator
                        # on the next token, so it only shows during gaps.
                        yield f"data: {json.dumps({'stage': payload})}\n\n"
                    elif chunk_kind == "debug":
                        # payload is already-serialized JSON of the debug trace.
                        debug_payload = json.loads(payload)
                        yield f"data: {json.dumps({'debug': debug_payload})}\n\n"
                    elif chunk_kind == "text_delta":
                        if not gen_started:
                            yield f"data: {json.dumps({'stage': 'generating'})}\n\n"
                            gen_started = True
                        full_response += payload
                        yield f"data: {json.dumps({'token': payload})}\n\n"
                completed_cleanly = True
            finally:
                # Persist whatever we streamed, even if the client disconnected
                # or an exception cut things short. Previously the message row
                # only got saved on a clean loop exit — a mid-stream drop left
                # orphaned user messages with no assistant reply in the
                # conversation, corrupting future turns' history.
                if full_response:
                    content_to_save = full_response
                    if not completed_cleanly:
                        content_to_save += "\n\n*(reply truncated — connection dropped mid-stream)*"
                    with stage("db: save assistant msg"):
                        row = {
                            "conversation_id": conversation_id,
                            "role": "assistant",
                            "content": content_to_save,
                        }
                        # Persist the debug trace so the Inspect card survives
                        # reloads (only when debug mode captured one).
                        if debug_payload is not None:
                            row["debug"] = debug_payload
                        sb.table("messages").insert(row).execute()

    yield f"data: {json.dumps({'done': True})}\n\n"


def _run_loop_and_stream_final(
    *,
    user_message: str,
    user_id: str,
    topic: str | None,
    keyword: str | None,
    model: str,
    mode: str,
    debug: bool = False,
    history: list[dict] | None,
    scope_folder_ids: list[str] | None = None,
    scope_filename: str | None = None,
) -> Generator[tuple[str, str], None, None]:
    """Tool-use loop that streams text deltas via Anthropic's streaming API.

    On every round, we open a stream. If the model calls a tool, no text
    was streamed (tool_use blocks arrive as their own event, not as text
    deltas), so nothing user-facing changes. If the model produces text,
    each chunk lands in the SSE feed as it's generated — first-token
    latency becomes just Anthropic's TTFT (~500-1500ms), not
    end-to-end generation time (~10s).
    """
    messages = list(history or []) + [{"role": "user", "content": user_message}]
    max_rounds = 10
    task, max_tokens, thinking_budget = _agent_params(model, mode)
    system_prompt, tools = _mode_config(mode)
    # Debug trace for the UI's Inspect card (reasoning, tool calls, retrieval).
    debug_trace: dict | None = (
        {"model": model, "reasoning": [], "tool_calls": [], "retrieval": []} if debug else None
    )

    for round_num in range(max_rounds):
        # Tell the UI what's happening before the (possibly long) model call:
        # deep mode reasons first, fast mode goes straight to searching.
        yield ("stage", "thinking" if thinking_budget else "searching")
        with stage(f"round {round_num + 1}: anthropic stream"):
            with stream_complete(
                task=task,
                max_tokens=max_tokens,
                thinking_budget=thinking_budget,
                system=system_prompt,
                messages=messages,
                tools=tools,
            ) as stream:
                # Anthropic's stream helper exposes text_stream (deltas) and
                # get_final_message() (assembled). Yield deltas as they arrive.
                for text in stream.text_stream:
                    if text:
                        yield ("text_delta", text)
                final = stream.get_final_message()

        if debug_trace is not None:
            for b in final.content:
                if getattr(b, "type", None) == "thinking":
                    text = getattr(b, "thinking", "") or ""
                    if text:
                        debug_trace["reasoning"].append({"round": round_num + 1, "text": text})

        if final.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": final.content})
            tool_uses = [b for b in final.content if b.type == "tool_use"]
            yield ("stage", "searching")

            def _run_tool(block, _indent: int = 1) -> dict:
                # Wrap execute_tool so a failing tool (Voyage 429, Mem0 down,
                # bad SQL) returns an is_error tool_result the model can
                # gracefully compose an apology around, instead of the
                # exception bubbling out of the generator and 500ing the SSE.
                with stage(f"tool: {block.name}", indent=_indent):
                    try:
                        result_text = execute_tool(
                            block.name,
                            block.input,
                            user_id,
                            topic,
                            keyword,
                            fast_mode=False,
                            scope_folder_ids=scope_folder_ids,
                            scope_filename=scope_filename,
                            debug_retrieval=(
                                debug_trace["retrieval"] if debug_trace is not None else None
                            ),
                        )
                    except Exception as exc:  # noqa: BLE001
                        return {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": f"Tool {block.name!r} raised: {exc}",
                            "is_error": True,
                        }
                return {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_text,
                }

            if len(tool_uses) > 1:
                with stage(f"{len(tool_uses)} tools (parallel)"):
                    with ThreadPoolExecutor(max_workers=len(tool_uses)) as pool:
                        futures = [submit_with_context(pool, _run_tool, b, 2) for b in tool_uses]
                        tool_results = [f.result() for f in futures]
            else:
                tool_results = [_run_tool(b) for b in tool_uses]

            if debug_trace is not None:
                for b, tr in zip(tool_uses, tool_results, strict=False):
                    debug_trace["tool_calls"].append(
                        {
                            "round": round_num + 1,
                            "name": b.name,
                            "input": b.input,
                            "result_preview": (tr.get("content") or "")[:1500],
                            "is_error": bool(tr.get("is_error")),
                        }
                    )

            messages.append({"role": "user", "content": tool_results})
            continue

        # No tool_use → the answer streamed above; loop is done.
        if debug_trace is not None:
            yield ("debug", json.dumps(debug_trace, default=str))
        return

    if debug_trace is not None:
        yield ("debug", json.dumps(debug_trace, default=str))
    yield ("text_delta", "I was unable to complete the request after multiple attempts.")
