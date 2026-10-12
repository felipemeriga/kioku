"""Agentic RAG pipeline: tool-use loop with streaming."""

import json
import logging
import queue as _queue
import threading
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor

from langsmith import traceable

from db.client import get_supabase, get_supabase_thread_safe
from services.ai_config import is_reasoning_model, resolve_chat
from services.llm import Task, complete, stream_complete
from services.metrics import collect_request, record, submit_with_context
from services.timing import request, stage
from services.tools import TOOL_DEFINITIONS, execute_tool

logger = logging.getLogger(__name__)

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
    model: str = "sonnet",
    mode: str = "deep",
    debug: bool = False,
    scope_folder_id: str | None = None,
    scope_filename: str | None = None,
) -> Generator[str, None, None]:
    """Agentic RAG pipeline: save message, run tool-use loop, stream response."""
    sb = get_supabase()

    # BYOK: resolve the user's chat provider/model/key. Defaults to anthropic
    # with api_key=None, which means "use the existing kioku Anthropic path".
    chat_cfg = resolve_chat(sb, user_id)

    # Resolve a folder scope to its subtree once — the agent may call the
    # search tool several times per turn.
    scope_folder_ids: list[str] | None = None
    if scope_folder_id:
        from services.scope import descendant_folder_ids

        scope_folder_ids = descendant_folder_ids(sb, scope_folder_id, user_id)

    _label = f"{model}/{mode}"
    # 1. Save the user message, set the title if still default, and fetch prior
    # history for the model (excluding the message we just saved). The turn's
    # timing/metrics are collected inside the generation thread below.
    sb.table("messages").insert(
        {"conversation_id": conversation_id, "role": "user", "content": user_message}
    ).execute()
    # Only auto-set the title if the conversation still has its default
    # null/placeholder title, so a user rename (PATCH /conversations/{id}) isn't
    # overwritten by every subsequent message. 'New conversation' is the default.
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
        sb.table("conversations").update({"title": user_message[:50]}).eq("id", conversation_id).eq(
            "user_id", user_id
        ).execute()
    history = (
        sb.table("messages")
        .select("role, content")
        .eq("conversation_id", conversation_id)
        .order("created_at")
        .execute()
    )
    prior_messages = [{"role": m["role"], "content": m["content"]} for m in history.data]
    # Drop the user message we just saved — the loop appends it itself.
    if prior_messages and prior_messages[-1] == {"role": "user", "content": user_message}:
        prior_messages = prior_messages[:-1]

    # 2. Run the agent loop in a BACKGROUND THREAD that pushes events to a queue;
    # the SSE response below just relays from the queue. Generation and the
    # assistant-message save therefore run to completion EVEN IF THE CLIENT
    # DISCONNECTS (user navigates away / closes the tab) — so the full answer is
    # persisted and shows up on reload, instead of being cancelled and saved
    # truncated mid-stream.
    events: _queue.Queue = _queue.Queue()
    _END = object()

    def _generate_and_save() -> None:
        sb_bg = get_supabase_thread_safe()
        full = ""
        debug_payload: dict | None = None
        usage_payload: dict | None = None
        try:
            with collect_request(f"rag chat turn ({_label})"), request(f"rag chat turn ({_label})"):
                for chunk_kind, payload in _run_loop_and_stream_final(
                    user_message=user_message,
                    user_id=user_id,
                    model=model,
                    mode=mode,
                    debug=debug,
                    history=prior_messages,
                    scope_folder_ids=scope_folder_ids,
                    scope_filename=scope_filename,
                    provider=chat_cfg["provider"],
                    chat_model=chat_cfg["model"],
                    api_key=chat_cfg["api_key"],
                ):
                    # Usage is captured for billing, not streamed to the client.
                    if chunk_kind == "usage":
                        usage_payload = json.loads(payload)
                        continue
                    events.put((chunk_kind, payload))
                    if chunk_kind == "text_delta":
                        full += payload
                    elif chunk_kind == "debug":
                        debug_payload = json.loads(payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("rag generation failed", exc_info=True)
            events.put(("error", str(exc)))
        finally:
            # Save the full assistant message regardless of client connection.
            if full:
                row: dict = {
                    "conversation_id": conversation_id,
                    "role": "assistant",
                    "content": full,
                }
                if debug_payload is not None:
                    row["debug"] = debug_payload
                try:
                    sb_bg.table("messages").insert(row).execute()
                except Exception:  # noqa: BLE001
                    logger.warning("failed to save assistant message", exc_info=True)
            # Record this turn's token usage (going-forward billing view).
            if (
                usage_payload
                and (
                    (usage_payload.get("input_tokens") or 0)
                    + (usage_payload.get("output_tokens") or 0)
                )
                > 0
            ):
                try:
                    sb_bg.table("chat_usage").insert(
                        {
                            "user_id": user_id,
                            "conversation_id": conversation_id,
                            "model": usage_payload.get("model") or model,
                            "input_tokens": usage_payload.get("input_tokens") or 0,
                            "output_tokens": usage_payload.get("output_tokens") or 0,
                        }
                    ).execute()
                except Exception:  # noqa: BLE001
                    logger.warning("failed to save chat usage", exc_info=True)
            events.put(_END)

    threading.Thread(target=_generate_and_save, name="rag-generate", daemon=True).start()

    # 3. Relay queue → SSE. If the client disconnects, this generator simply
    # stops being iterated; the thread keeps running and saves the full answer.
    gen_started = False
    while True:
        item = events.get()
        if item is _END:
            break
        kind, payload = item
        if kind == "stage":
            yield f"data: {json.dumps({'stage': payload})}\n\n"
        elif kind == "debug":
            yield f"data: {json.dumps({'debug': json.loads(payload)})}\n\n"
        elif kind == "error":
            yield f"data: {json.dumps({'error': payload})}\n\n"
        elif kind == "text_delta":
            if not gen_started:
                yield f"data: {json.dumps({'stage': 'generating'})}\n\n"
                gen_started = True
            yield f"data: {json.dumps({'token': payload})}\n\n"

    yield f"data: {json.dumps({'done': True})}\n\n"


def _run_loop_and_stream_final(
    *,
    user_message: str,
    user_id: str,
    model: str,
    mode: str,
    debug: bool = False,
    history: list[dict] | None,
    scope_folder_ids: list[str] | None = None,
    scope_filename: str | None = None,
    provider: str = "anthropic",
    chat_model: str | None = None,
    api_key: str | None = None,
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

    # BYOK: non-Anthropic providers run a parallel LiteLLM loop. Anthropic (the
    # default / no-BYOK case) falls through to the existing untouched code below.
    if provider != "anthropic":
        yield from _run_loop_litellm(
            provider=provider,
            model=chat_model or "",
            api_key=api_key,
            mode=mode,
            system_prompt=system_prompt,
            tools=tools,
            messages=messages,
            user_id=user_id,
            scope_folder_ids=scope_folder_ids,
            scope_filename=scope_filename,
            debug_trace=debug_trace,
            max_rounds=max_rounds,
        )
        return

    # Accumulate token usage across every round of this turn (tool rounds + the
    # final answer) for the Settings usage/cost view.
    usage_in = 0
    usage_out = 0

    def _usage_event() -> tuple[str, str]:
        return (
            "usage",
            json.dumps({"input_tokens": usage_in, "output_tokens": usage_out, "model": model}),
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
                u = getattr(final, "usage", None)
                if u:
                    usage_in += getattr(u, "input_tokens", 0) or 0
                    usage_out += getattr(u, "output_tokens", 0) or 0

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
        yield _usage_event()
        return

    if debug_trace is not None:
        yield ("debug", json.dumps(debug_trace, default=str))
    yield ("text_delta", "I was unable to complete the request after multiple attempts.")
    yield _usage_event()


def _anthropic_tools_to_openai(tools: list[dict]) -> list[dict]:
    """Translate our Anthropic-format tool defs to OpenAI function-tool format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def _to_openai_messages(system_prompt: str, messages: list[dict]) -> list[dict]:
    """Seed the OpenAI-format message list: system prompt + plain chat history.

    `messages` here is prior history + the current user turn, all plain
    {role, content:str} — the tool-call/tool-result turns are appended by the
    loop itself in OpenAI format."""
    out: list[dict] = [{"role": "system", "content": system_prompt}]
    for m in messages:
        out.append({"role": m["role"], "content": m["content"]})
    return out


def _run_loop_litellm(
    *,
    provider: str,
    model: str,
    api_key: str | None,
    mode: str,
    system_prompt: str,
    tools: list[dict],
    messages: list[dict],
    user_id: str,
    scope_folder_ids: list[str] | None,
    scope_filename: str | None,
    debug_trace: dict | None,
    max_rounds: int,
) -> Generator[tuple[str, str], None, None]:
    """Tool-use streaming loop for non-Anthropic providers (OpenAI / DeepSeek)
    via LiteLLM. Mirrors the SSE event contract of the Anthropic loop
    (text_delta / stage / debug / usage) so nothing downstream changes.

    Caveats vs the Anthropic path: no prompt caching, and "deep mode" maps to
    reasoning_effort only on reasoning-capable models (else it just runs)."""
    import litellm

    oai_messages = _to_openai_messages(system_prompt, messages)
    oai_tools = _anthropic_tools_to_openai(tools)
    use_reasoning = mode == "deep" and is_reasoning_model(provider, model)

    usage_in = 0
    usage_out = 0

    def _usage_event() -> tuple[str, str]:
        return (
            "usage",
            json.dumps({"input_tokens": usage_in, "output_tokens": usage_out, "model": model}),
        )

    for round_num in range(max_rounds):
        yield ("stage", "thinking" if use_reasoning else "searching")
        kwargs: dict = {
            "model": f"{provider}/{model}",
            "messages": oai_messages,
            "tools": oai_tools,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if api_key:
            kwargs["api_key"] = api_key
        if use_reasoning:
            kwargs["reasoning_effort"] = "medium"

        tool_calls: dict[int, dict] = {}
        with stage(f"round {round_num + 1}: {provider} stream"):
            for chunk in litellm.completion(**kwargs):
                choices = getattr(chunk, "choices", None) or []
                if choices:
                    delta = getattr(choices[0], "delta", None)
                    if delta is not None:
                        content = getattr(delta, "content", None)
                        if content:
                            yield ("text_delta", content)
                        for tc in getattr(delta, "tool_calls", None) or []:
                            idx = getattr(tc, "index", 0) or 0
                            slot = tool_calls.setdefault(idx, {"id": None, "name": "", "args": ""})
                            if getattr(tc, "id", None):
                                slot["id"] = tc.id
                            fn = getattr(tc, "function", None)
                            if fn is not None:
                                if getattr(fn, "name", None):
                                    slot["name"] = fn.name
                                if getattr(fn, "arguments", None):
                                    slot["args"] += fn.arguments
                usage = getattr(chunk, "usage", None)
                if usage:
                    usage_in += getattr(usage, "prompt_tokens", 0) or 0
                    usage_out += getattr(usage, "completion_tokens", 0) or 0

        if not tool_calls:
            # No tool calls → the answer streamed above; loop is done.
            if debug_trace is not None:
                yield ("debug", json.dumps(debug_trace, default=str))
            yield _usage_event()
            return

        ordered = [tool_calls[i] for i in sorted(tool_calls)]
        oai_messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": s["id"],
                        "type": "function",
                        "function": {"name": s["name"], "arguments": s["args"] or "{}"},
                    }
                    for s in ordered
                ],
            }
        )
        yield ("stage", "searching")
        for s in ordered:
            try:
                args = json.loads(s["args"] or "{}")
            except json.JSONDecodeError:
                args = {}
            with stage(f"tool: {s['name']}", indent=1):
                try:
                    result_text = execute_tool(
                        s["name"],
                        args,
                        user_id,
                        fast_mode=False,
                        scope_folder_ids=scope_folder_ids,
                        scope_filename=scope_filename,
                        debug_retrieval=(
                            debug_trace["retrieval"] if debug_trace is not None else None
                        ),
                    )
                    is_error = False
                except Exception as exc:  # noqa: BLE001
                    result_text = f"Tool {s['name']!r} raised: {exc}"
                    is_error = True
            if debug_trace is not None:
                debug_trace["tool_calls"].append(
                    {
                        "round": round_num + 1,
                        "name": s["name"],
                        "input": args,
                        "result_preview": (result_text or "")[:1500],
                        "is_error": is_error,
                    }
                )
            oai_messages.append({"role": "tool", "tool_call_id": s["id"], "content": result_text})

    if debug_trace is not None:
        yield ("debug", json.dumps(debug_trace, default=str))
    yield ("text_delta", "I was unable to complete the request after multiple attempts.")
    yield _usage_event()
