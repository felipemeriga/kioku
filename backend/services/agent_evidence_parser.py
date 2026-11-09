"""Lossless-source locators and a bounded, rebuildable conversation projection."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from dateutil.parser import isoparse

from services.agent_evidence_models import event_id

PREVIEW_BYTES = 4096


def bounded_text(value: str, length=PREVIEW_BYTES) -> str:
    return value.encode("utf-8")[:length].decode("utf-8", errors="ignore")


def instant(value):
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()
        parsed = isoparse(str(value))
        if parsed.tzinfo:
            return parsed.astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError, TypeError):
        pass
    return None


def content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(content_text(part) for part in content)
    if isinstance(content, dict):
        if "text" in content:
            return str(content["text"])
        if "content" in content:
            return content_text(content["content"])
        return json.dumps(content, ensure_ascii=False)
    return str(content) if content is not None else ""


def project_record(record: dict, agent: str, state: dict) -> dict:
    """No model invocation, no filesystem/URL dereferencing, no body persistence."""
    kind = record.get("type", "unknown")
    p = record.get("payload") if agent == "codex" else record.get("message")
    p = p if isinstance(p, dict) else {}
    role, event_type, text = "system", kind, ""
    native_id = record.get("uuid") or p.get("id")
    call_id = p.get("call_id")
    display = False
    if agent == "claude_code" and kind in ("user", "assistant"):
        role = "user" if kind == "user" else "assistant"
        event_type = "message"
        display = True
        content = p.get("content", "")
        text = content_text(content)
        if isinstance(content, list):
            tool = next(
                (
                    x
                    for x in content
                    if isinstance(x, dict) and x.get("type") in ("tool_use", "tool_result")
                ),
                None,
            )
            if tool:
                event_type = "tool_call" if tool["type"] == "tool_use" else "tool_result"
                role = "tool"
                call_id = tool.get("id") or tool.get("tool_use_id")
        # Native toolUseResult can contain a richer body than the rendered preview.
        detail = record.get("toolUseResult")
        if isinstance(detail, dict):
            richer = content_text(detail.get("stdout"))
            if len(richer) > len(text):
                text = richer
        if role == "user":
            state["turn_id"] = str(native_id) if native_id else state.get("turn_id")
    elif agent == "codex":
        if kind == "turn_context":
            state["turn_id"] = p.get("turn_id")
        if kind == "session_meta":
            if p.get("id") == state.get("native_session_id"):
                state["own_context"] = True
            elif p.get("parent_thread_id") or p.get("id"):
                state.setdefault("own_context", False)
        if kind == "response_item":
            event_type = p.get("type", "unknown")
            if event_type == "message":
                role = p.get("role", "system")
                text = content_text(p.get("content"))
                display = role in ("user", "assistant")
            elif event_type in ("function_call", "custom_tool_call"):
                role, display = "tool", True
                event_type = "tool_call"
                text = (
                    str(p.get("name", "tool"))
                    + "\n"
                    + content_text(p.get("arguments", p.get("input")))
                )
            elif event_type in ("function_call_output", "custom_tool_call_output"):
                role, event_type, display = "tool", "tool_result", True
                text = content_text(p.get("output"))
        elif kind == "event_msg":
            item = p.get("item", {})
            if p.get("type") == "item_completed" and isinstance(item, dict):
                if "aggregated_output" in item:
                    role, event_type, display = "tool", "tool_result", True
                    text = content_text(item["aggregated_output"])
                    call_id = item.get("id")
                elif item.get("type") in ("UserMessage", "AgentMessage"):
                    role = "user" if item["type"] == "UserMessage" else "assistant"
                    event_type, display = "message", True
                    text = content_text(item.get("content"))
            elif p.get("type") == "user_message":
                role, event_type, display = "user", "message", True
                text = content_text(p.get("message"))
        if p.get("turn_id"):
            state["turn_id"] = p["turn_id"]
    if kind == "compacted" or (kind == "system" and "compact" in record.get("subtype", "")):
        text, event_type, display = "Context compacted", "compaction", True
    truncated = "Warning: truncated output" in text or "[Output truncated" in text
    return {
        "event_at": instant(record.get("timestamp")),
        "role": role,
        "event_type": event_type,
        "native_id": str(native_id) if native_id else None,
        "turn_id": state.get("turn_id"),
        "call_id": str(call_id) if call_id else None,
        "parent_id": record.get("parentUuid"),
        "inherited": state.get("own_context") is False,
        "displayable": display,
        "content_preview": bounded_text(text),
        "source_truncated": truncated,
        "content_length": len(text.encode()),
        "_content": text,
    }


def iter_segment(
    raw: bytes, descriptor: dict, session: dict, state: dict, *, include_content=False
):
    state.setdefault("native_session_id", session["native_session_id"])
    state.setdefault(
        "own_context", session["agent"] == "claude_code" or session.get("parent_session_id") is None
    )
    offset = 0
    if not raw.endswith(b"\n") or raw.count(b"\n") != descriptor["record_count"]:
        raise ValueError("Segment is not a complete declared record range")
    for index in range(descriptor["first_record"], descriptor["last_record"] + 1):
        end = raw.index(b"\n", offset) + 1
        line = raw[offset:end]
        try:
            d = json.loads(line)
            if not isinstance(d, dict):
                raise ValueError("Native record is not an object")
            projection = project_record(d, session["agent"], state)
        except (ValueError, UnicodeDecodeError, TypeError):
            projection = {
                "event_at": None,
                "role": "system",
                "event_type": "parse_error",
                "displayable": False,
                "content_preview": "Uninterpretable original record",
                "source_truncated": False,
            }
        if not include_content:
            projection.pop("_content", None)
        yield {
            **projection,
            "event_id": event_id(
                session["folder_id"],
                session["agent"],
                session["native_session_id"],
                descriptor["stream_id"],
                descriptor["generation"],
                index,
            ),
            "stream_id": descriptor["stream_id"],
            "generation": descriptor["generation"],
            "record_sequence": index,
            "byte_offset": offset,
            "byte_length": len(line),
        }
        offset += len(line)


def parse_segment(raw: bytes, descriptor: dict, session: dict, initial_state=None):
    state = dict(initial_state or {})
    events = list(iter_segment(raw, descriptor, session, state))
    return events, state
