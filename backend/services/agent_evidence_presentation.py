"""Deterministic, read-time native content presentation; originals are untouched."""

import hashlib
import json
import math
import re
import shlex

from services.agent_evidence_parser import bounded_text, content_text

VERSION = 1
MAX_BLOCKS = 128
MAX_PRESENTATION_BYTES = 65536


def _reject_nonfinite(_):
    raise ValueError("nonfinite JSON")


def _json(value):
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value, parse_constant=_reject_nonfinite)
    except (ValueError, TypeError, RecursionError):
        return None


def _field_text(value, tool, limit=2048):
    text = str(value)
    shortened = bounded_text(text, limit)
    if shortened != text:
        tool["_viewer_truncated"] = True
    return shortened


def _call_identifier(value, tool):
    text = str(value)
    if len(text.encode()) <= 512:
        return text
    tool["_viewer_truncated"] = True
    # Keep distinct oversized native identities distinct when the UI pairs tool events.
    return bounded_text(text, 430) + "#sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _metadata(source, tool):
    if not isinstance(source, dict):
        return
    if source.get("truncated") is True:
        tool["_source_truncated"] = True
    aliases = {
        "cwd": "cwd",
        "exit_code": "exit_code",
        "duration_seconds": "duration_seconds",
        "wall_time_seconds": "orchestration_seconds",
        "status": "status",
        "call_id": "call_id",
    }
    for key, target in aliases.items():
        value = source.get(key)
        if isinstance(value, float) and not math.isfinite(value):
            continue
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            normalized = _field_text(value, tool) if isinstance(value, str) else value
            if target == "orchestration_seconds" and target in tool:
                tool.setdefault("duration_seconds", normalized)
            else:
                tool[target] = normalized
    for key in ("duration_ms", "durationMs"):
        value = source.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            tool["duration_seconds"] = value / 1000
    if isinstance(source.get("exitCode"), int):
        tool["exit_code"] = source["exitCode"]
    for key in ("cmd", "command", "command_line"):
        value = source.get(key)
        if isinstance(value, str):
            tool["command_text"] = _field_text(value, tool, 4096)
            break
        if isinstance(value, list) and all(isinstance(x, str) for x in value):
            tool["command_text"] = _field_text(shlex.join(value), tool, 4096)
            break


def _tool_output(value, tool, depth=0):
    if depth > 5:
        return [{"kind": "text", "text": content_text(value)}]
    decoded = _json(value)
    if isinstance(decoded, str):
        return _tool_output(decoded, tool, depth + 1)
    if isinstance(value, list):
        blocks = []
        maximum = tool.get("_max_blocks")
        if maximum is not None and len(value) > maximum:
            tool["_viewer_truncated"] = True
        for part in value[:maximum]:
            if (
                isinstance(part, dict)
                and part.get("type") in {"text", "input_text", "output_text"}
                and set(part) <= {"type", "text"}
            ):
                blocks.extend(_tool_output(part.get("text", ""), tool, depth + 1))
            else:
                blocks.extend(_tool_output(part, tool, depth + 1))
            if maximum is not None and len(blocks) >= maximum:
                if len(blocks) > maximum or part is not value[-1]:
                    tool["_viewer_truncated"] = True
                blocks = blocks[:maximum]
                break
        return blocks
    envelope = decoded if isinstance(decoded, dict) else value
    if isinstance(envelope, dict):
        transport_keys = {
            "output",
            "aggregated_output",
            "content",
            "stdout",
            "stderr",
            "metadata",
            "chunk_id",
            "wall_time_seconds",
            "exit_code",
            "original_token_count",
            "duration_seconds",
            "duration_ms",
            "durationMs",
            "exitCode",
            "status",
            "session_id",
            "cwd",
            "call_id",
            "truncated",
        }
        metadata_keys = transport_keys - {
            "output",
            "aggregated_output",
            "content",
            "stdout",
            "stderr",
            "metadata",
        }
        metadata = envelope.get("metadata")
        recognized = (
            set(envelope) <= transport_keys
            and (metadata is None or isinstance(metadata, dict) and set(metadata) <= metadata_keys)
            and any(
                key in envelope
                for key in (
                    "stdout",
                    "stderr",
                    "metadata",
                    "chunk_id",
                    "wall_time_seconds",
                    "exit_code",
                    "duration_seconds",
                )
            )
        )
        if recognized:
            _metadata(envelope, tool)
            _metadata(metadata, tool)
            outputs = [
                envelope[key] for key in ("stdout", "stderr") if isinstance(envelope.get(key), str)
            ]
            if not outputs:
                for key in ("output", "aggregated_output", "content"):
                    if key in envelope:
                        outputs = [envelope[key]]
                        break
            if outputs:
                return [
                    block for output in outputs for block in _tool_output(output, tool, depth + 1)
                ]
        # Business JSON and unknown envelope fields are never dropped or guessed away.
        return [{"kind": "json", "text": json.dumps(envelope, ensure_ascii=False, indent=2)}]
    if isinstance(decoded, (list, int, float, bool)) or value is None:
        return [{"kind": "json", "text": json.dumps(decoded, ensure_ascii=False, indent=2)}]
    text = value if isinstance(value, str) else content_text(value)
    # Recognize only the native command-result header at the start, never arbitrary prose.
    match = re.match(
        r"\A((?:(?:Chunk ID:|Wall time:|Process exited with code |Exit code:|"
        r"Original token count:|Session ID:|Process running with session ID )[^\n]*\n)+)"
        r"(?:Final output:|Output:)\n",
        text,
    )
    if match:
        header = match.group(1)
        duration = re.search(r"Wall time:\s*([0-9.]+)\s*seconds", header)
        exit_code = re.search(r"(?:Process exited with code |Exit code:\s*)(-?\d+)", header)
        if duration:
            target = (
                "duration_seconds" if "orchestration_seconds" in tool else "orchestration_seconds"
            )
            tool[target] = float(duration.group(1))
        if exit_code:
            tool["exit_code"] = int(exit_code.group(1))
        text = text[match.end() :]
        return _tool_output(text, tool, depth + 1)
    return [{"kind": "terminal", "text": text}]


def present(record, agent, event=None, limit_bytes=4096, max_blocks=MAX_BLOCKS):
    """Native boundaries retained; JSON is marked JSON only when complete and valid."""
    event = event or {}
    payload = record.get("payload") if agent == "codex" else record.get("message")
    payload = payload if isinstance(payload, dict) else {}
    tool = {"_max_blocks": max_blocks}
    _metadata(payload, tool)
    event_type = event.get("event_type")
    call_id = event.get("call_id") or payload.get("call_id")
    if call_id:
        tool["call_id"] = _call_identifier(call_id, tool)
    blocks = []
    if agent == "codex" and payload.get("type") in {"function_call", "custom_tool_call"}:
        tool["name"] = str(payload.get("name", "tool"))[:256]
        args = payload.get("arguments", payload.get("input", ""))
        parsed = _json(args)
        _metadata(parsed, tool)
        blocks = [
            {
                "kind": "json" if parsed is not None else "text",
                "text": json.dumps(parsed, ensure_ascii=False, indent=2)
                if parsed is not None
                else content_text(args),
            }
        ]
        if (
            payload.get("type") == "custom_tool_call"
            and payload.get("name") in {"exec", "functions.exec"}
            and isinstance(args, str)
        ):
            blocks = [{"kind": "code", "text": args, "language": "javascript"}]
    elif agent == "codex" and (
        payload.get("type") in {"function_call_output", "custom_tool_call_output"}
        or event_type == "tool_result"
    ):
        item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
        _metadata(item, tool)
        value = payload.get(
            "output", item.get("aggregated_output", payload.get("aggregated_output", ""))
        )
        blocks = _tool_output(value, tool)
    else:
        item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
        content = payload.get(
            "content", payload.get("message", item.get("content", event.get("content_preview", "")))
        )
        if not isinstance(content, list):
            content = [{"type": "text", "text": content}]
        if max_blocks is not None and len(content) > max_blocks:
            tool["_viewer_truncated"] = True
        for part in content[:max_blocks]:
            if not isinstance(part, dict):
                blocks.append({"kind": "text", "text": content_text(part)})
                continue
            kind = part.get("type")
            if kind == "tool_use":
                tool["name"] = str(part.get("name", "tool"))[:256]
                tool["call_id"] = _call_identifier(part.get("id", call_id or ""), tool)
                args = part.get("input", {})
                _metadata(args, tool)
                blocks.append(
                    {"kind": "json", "text": json.dumps(args, ensure_ascii=False, indent=2)}
                )
            elif kind == "tool_result":
                tool["call_id"] = _call_identifier(part.get("tool_use_id", call_id or ""), tool)
                detail = record.get("toolUseResult")
                blocks.extend(
                    _tool_output(
                        detail
                        if isinstance(detail, dict)
                        and any(k in detail for k in ("stdout", "stderr", "output"))
                        else part.get("content", ""),
                        tool,
                    )
                )
            elif kind == "code":
                block = {
                    "kind": "code",
                    "text": content_text(part.get("text", part.get("code", ""))),
                }
                if isinstance(part.get("language"), str):
                    block["language"] = part["language"][:64]
                blocks.append(block)
            elif kind in {"text", "input_text", "output_text"}:
                blocks.append({"kind": "markdown", "text": content_text(part.get("text", ""))})
            else:
                blocks.append(
                    {"kind": "json", "text": json.dumps(part, ensure_ascii=False, indent=2)}
                )
    if agent == "codex" and (
        payload.get("type")
        in {"function_call", "custom_tool_call", "function_call_output", "custom_tool_call_output"}
        or event_type == "tool_result"
    ):
        known_payload = {
            "type",
            "name",
            "arguments",
            "input",
            "call_id",
            "id",
            "output",
            "item",
            "aggregated_output",
            "turn_id",
            "status",
            "cwd",
            "exit_code",
            "duration_seconds",
            "wall_time_seconds",
            "duration_ms",
            "durationMs",
            "exitCode",
            "command",
            "cmd",
            "command_line",
        }
        unknown = {key: value for key, value in payload.items() if key not in known_payload}
        if unknown:
            blocks.append(
                {"kind": "json", "text": json.dumps(unknown, ensure_ascii=False, indent=2)}
            )
        item = payload.get("item")
        if isinstance(item, dict):
            known_item = known_payload | {"process_id", "session_id"}
            unknown_item = {key: value for key, value in item.items() if key not in known_item}
            if unknown_item:
                blocks.append(
                    {"kind": "json", "text": json.dumps(unknown_item, ensure_ascii=False, indent=2)}
                )
    source_truncated = bool(
        event.get("source_truncated")
        or tool.get("_source_truncated")
        or record.get("truncated") is True
        or payload.get("truncated") is True
    )
    for block in blocks:
        if "Warning: truncated output" in block["text"] or "[Output truncated" in block["text"]:
            source_truncated = True
    bounded = []
    remaining = limit_bytes
    clipped = bool(tool.pop("_viewer_truncated", False))
    if max_blocks is not None and len(blocks) > max_blocks:
        clipped = True
    for block in blocks[:max_blocks]:
        text = block["text"]
        if remaining <= 0:
            clipped = True
            break
        actual = len(text.encode())
        shortened = bounded_text(text, remaining)
        trimmed = actual > remaining
        # A prefix of JSON is text, never a complete structured document.
        bounded.append(
            {
                **block,
                "kind": "text" if trimmed and block["kind"] == "json" else block["kind"],
                "text": shortened,
                "viewer_truncated": trimmed,
            }
        )
        remaining -= len(shortened.encode())
        clipped = clipped or trimmed
    tool = {key: value for key, value in tool.items() if not key.startswith("_")}
    result = {
        "version": VERSION,
        "blocks": bounded,
        **({"tool": tool} if tool else {}),
        "viewer_truncated": clipped,
        "source_truncated": source_truncated,
    }
    if (
        max_blocks is not None
        and len(json.dumps(result, ensure_ascii=False).encode()) > MAX_PRESENTATION_BYTES
    ):
        # Account for control-character escaping and block/metadata overhead, not text alone.
        text = bounded_text("\n".join(block["text"] for block in bounded), min(limit_bytes, 4096))
        result["blocks"] = [{"kind": "text", "text": text, "viewer_truncated": True}]
        result["viewer_truncated"] = True
        if len(json.dumps(result, ensure_ascii=False).encode()) > MAX_PRESENTATION_BYTES:
            result.pop("tool", None)
    return result


def fragment_presentation(text, source_truncated=False):
    return {
        "version": VERSION,
        "blocks": [{"kind": "text", "text": text, "viewer_truncated": True}],
        "viewer_truncated": True,
        "source_truncated": bool(source_truncated),
    }
