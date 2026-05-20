"""Agentic RAG pipeline: tool-use loop with streaming."""

import json
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor

from langsmith import traceable

from db.client import get_supabase
from services.llm import Task, complete
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
            messages = [{"role": m["role"], "content": m["content"]} for m in history.data]

        # 2. Tool-use loop (max 10 rounds to prevent runaway)
        full_response = ""
        max_rounds = 10

        yield f"data: {json.dumps({'stage': 'searching'})}\n\n"

        for round_num in range(max_rounds):
            with stage(f"round {round_num + 1}: anthropic call"):
                response = complete(
                    task=Task.RAG_AGENT,
                    max_tokens=1024,
                    system=SYSTEM_PROMPT,
                    messages=messages,
                    tools=TOOL_DEFINITIONS,
                )

            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})

                tool_uses = [b for b in response.content if b.type == "tool_use"]

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
                    }

                if len(tool_uses) > 1:
                    # Claude's parallel tool use: run them concurrently instead of
                    # blocking on each in sequence.
                    with stage(f"{len(tool_uses)} tools (parallel)"):
                        with ThreadPoolExecutor(max_workers=len(tool_uses)) as pool:
                            tool_results = list(
                                pool.map(lambda b: _run_tool(b, _indent=2), tool_uses)
                            )
                else:
                    tool_results = [_run_tool(b) for b in tool_uses]

                messages.append({"role": "user", "content": tool_results})

                doc_count = 0
                for tr in tool_results:
                    content = tr.get("content", "")
                    if isinstance(content, str):
                        doc_count += content.count("Source:")
                yield f"data: {json.dumps({'stage': 'analyzing', 'docs': doc_count})}\n\n"

                continue

            # Claude is done with tools — stream the final text response
            yield f"data: {json.dumps({'stage': 'generating'})}\n\n"

            for block in response.content:
                if hasattr(block, "text"):
                    full_response += block.text
                    yield f"data: {json.dumps({'token': block.text})}\n\n"
            break
        else:
            yield f"data: {json.dumps({'stage': 'generating'})}\n\n"
            full_response = "I was unable to complete the request after multiple attempts."
            yield f"data: {json.dumps({'token': full_response})}\n\n"

        with stage("db: save assistant msg"):
            sb.table("messages").insert(
                {
                    "conversation_id": conversation_id,
                    "role": "assistant",
                    "content": full_response,
                }
            ).execute()

    yield f"data: {json.dumps({'done': True})}\n\n"
