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

SYSTEM_PROMPT = """You are a helpful assistant with access to tools.

You have three tools available:
1. knowledge_base_search - Search the user's uploaded documents. The tool already performs \
internal query rewriting and multi-query expansion, so issue ONE focused search per turn with \
the user's best single question. Do not decompose the question into sub-queries yourself — the \
tool covers that internally.
2. query_documents_metadata - Query structured info about the user's documents (counts, types, \
topics).
3. web_search - Search the web when the knowledge base does not have the answer.

Pick one tool per turn unless you genuinely need two different tools (e.g., knowledge_base_search \
plus web_search). Do not call the same tool more than once per turn — pick the best query.
If a tool returns no results, try a different approach or a different tool on the next turn.
When answering, cite your sources when possible."""


@traceable(name="answer_question", run_type="chain")
def answer_question(
    user_message: str,
    user_id: str,
    topic: str | None = None,
    keyword: str | None = None,
    fast_mode: bool = False,
    history: list[dict] | None = None,
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

    for round_num in range(max_rounds):
        rounds_used = round_num + 1
        with stage(f"round {round_num + 1}: anthropic call"):
            response = complete(
                task=Task.RAG_AGENT,
                # 1024 truncated rich answers on comparison/multi-hop questions.
                # Haiku supports up to 8192; 4096 is plenty for thorough answers
                # without leaving the runaway-loop ceiling too open.
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=TOOL_DEFINITIONS,
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
                        fast_mode=fast_mode,
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
    fast_mode: bool = False,
) -> Generator[str, None, None]:
    """Agentic RAG pipeline: save message, run tool-use loop, stream response."""
    sb = get_supabase()

    with collect_request(f"rag chat turn ({'fast' if fast_mode else 'full'})"):
        with request(f"rag chat turn ({'fast' if fast_mode else 'full'})"):
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
                    .select("title").eq("id", conversation_id).eq("user_id", user_id)
                    .limit(1).execute().data
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

            yield f"data: {json.dumps({'stage': 'searching'})}\n\n"

            # 2. Run the tool-use loop, then stream the FINAL assistant text
            # from Anthropic as it generates. Previously we blocked on
            # answer_question and emitted the whole reply as a single 'token'
            # event, giving fake streaming with ~10s first-token latency.
            full_response = ""
            gen_started = False
            completed_cleanly = False
            try:
                for chunk_kind, payload in _run_loop_and_stream_final(
                    user_message=user_message,
                    user_id=user_id,
                    topic=topic,
                    keyword=keyword,
                    fast_mode=fast_mode,
                    history=prior_messages,
                ):
                    if chunk_kind == "text_delta":
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
                        content_to_save += (
                            "\n\n*(reply truncated — connection dropped mid-stream)*"
                        )
                    with stage("db: save assistant msg"):
                        sb.table("messages").insert(
                            {
                                "conversation_id": conversation_id,
                                "role": "assistant",
                                "content": content_to_save,
                            }
                        ).execute()

    yield f"data: {json.dumps({'done': True})}\n\n"


def _run_loop_and_stream_final(
    *,
    user_message: str,
    user_id: str,
    topic: str | None,
    keyword: str | None,
    fast_mode: bool,
    history: list[dict] | None,
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

    for round_num in range(max_rounds):
        with stage(f"round {round_num + 1}: anthropic stream"):
            with stream_complete(
                task=Task.RAG_AGENT,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=TOOL_DEFINITIONS,
            ) as stream:
                # Anthropic's stream helper exposes text_stream (deltas) and
                # get_final_message() (assembled). Yield deltas as they arrive.
                for text in stream.text_stream:
                    if text:
                        yield ("text_delta", text)
                final = stream.get_final_message()

        if final.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": final.content})
            tool_uses = [b for b in final.content if b.type == "tool_use"]

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
                            fast_mode=fast_mode,
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

            messages.append({"role": "user", "content": tool_results})
            continue

        # No tool_use → the answer streamed above; loop is done.
        return

    yield ("text_delta", "I was unable to complete the request after multiple attempts.")
