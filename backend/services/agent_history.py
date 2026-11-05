"""Bounded, owner-scoped original-evidence calendar navigation."""

import base64
import json
from datetime import date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from services.agent_evidence import fail, rpc
from services.agent_evidence_models import canonical


def validate(timezone, agent):
    try:
        ZoneInfo(timezone)
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        fail("invalid_timezone", 422)
    if agent not in (None, "codex", "claude_code"):
        fail("invalid_agent", 422)


def days(store, start: date, end: date, timezone="UTC", agent=None):
    validate(timezone, agent)
    if end < start or (end - start).days > 62:
        fail("date_range_exceeds_limit", 422)
    return {
        "timezone": timezone,
        "days": rpc(
            store.sb,
            "agent_history_days",
            {
                "p_user_id": store.user_id,
                "p_folder_id": store.folder_id,
                "p_from": start.isoformat(),
                "p_to": end.isoformat(),
                "p_timezone": timezone,
                "p_agent": agent,
            },
        ),
    }


def sessions(store, day: date, timezone="UTC", cursor=None, limit=50, agent=None):
    validate(timezone, agent)
    scope = [1, store.user_id, store.folder_id, day.isoformat(), timezone, agent]
    before_at = before_id = None
    if cursor:
        try:
            if len(cursor) > 2048:
                raise ValueError("oversized")
            value = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
            if not isinstance(value, list) or len(value) != 8 or value[:6] != scope:
                raise ValueError("scope")
            before_at, before_id = value[6:]
            if not datetime.fromisoformat(before_at.replace("Z", "+00:00")).tzinfo:
                raise ValueError("timezone")
            UUID(before_id)
        except (ValueError, TypeError, IndexError, AttributeError):
            fail("invalid_cursor", 422)
    rows = rpc(
        store.sb,
        "agent_history_sessions",
        {
            "p_user_id": store.user_id,
            "p_folder_id": store.folder_id,
            "p_date": day.isoformat(),
            "p_timezone": timezone,
            "p_limit": limit + 1,
            "p_before_at": before_at,
            "p_before_id": before_id,
            "p_agent": agent,
        },
    )
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = (
            base64.urlsafe_b64encode(canonical(scope + [last["day_last_event_at"], last["id"]]))
            .decode()
            .rstrip("=")
        )
    return {
        "sessions": rows[:limit],
        "next_cursor": next_cursor,
        "timezone": timezone,
        "date": day.isoformat(),
    }
