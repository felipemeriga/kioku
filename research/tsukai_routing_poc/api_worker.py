"""Runs only through docker exec: uses container's existing API environment."""

import json
import sys
import time

import anthropic

client = anthropic.Anthropic(timeout=90, max_retries=0)
for line in sys.stdin:
    req = json.loads(line)
    started = time.monotonic()
    try:
        messages = [{"role": "user", "content": req["prompt"]}]
        rounds = 0
        tool_calls = 0
        tools = (
            [
                {
                    "name": "knowledge_base_search",
                    "description": "Read source-grounded fixture facts",
                    "input_schema": {
                        "type": "object",
                        "properties": {"query": {"type": "string"}},
                        "required": ["query"],
                    },
                }
            ]
            if req.get("agent")
            else []
        )
        while True:
            rounds += 1
            with client.messages.stream(
                model=req["model"],
                max_tokens=512,
                system=[
                    {
                        "type": "text",
                        "text": req["system"],
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=messages,
                tools=tools,
            ) as stream:
                for text in stream.text_stream:
                    print(json.dumps({"type": "text", "text": text}), flush=True)
                result = stream.get_final_message()
            if result.stop_reason != "tool_use":
                break
            messages.append({"role": "assistant", "content": result.content})
            results = []
            for block in result.content:
                if block.type == "tool_use":
                    tool_calls += 1
                    evidence = "[1] worker.py:1 MAX_ATTEMPTS = 7; README.md PostgreSQL outbox with event_id idempotency. No deployment evidence."
                    print(
                        json.dumps(
                            {"type": "tool", "name": block.name, "evidence": evidence}
                        ),
                        flush=True,
                    )
                    results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": evidence,
                        }
                    )
            messages.append({"role": "user", "content": results})
            if rounds >= 4:
                raise RuntimeError("tool budget exceeded")
        print(
            json.dumps(
                {
                    "type": "result",
                    "text": "".join(getattr(b, "text", "") for b in result.content),
                    "model": result.model,
                    "usage": result.usage.model_dump(),
                    "provider_s": time.monotonic() - started,
                    "provider_message_id": result.id,
                    "success": result.stop_reason == "end_turn",
                    "rounds": rounds,
                    "tool_calls": tool_calls,
                }
            ),
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {"type": "result", "success": False, "error_type": type(exc).__name__}
            ),
            flush=True,
        )
