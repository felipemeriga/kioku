"""``POST /internal/events`` — consume a gateway event envelope."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..events import parser
from ..state import LedgerState, get_state
from .schemas import EventAck

router = APIRouter(prefix="/internal", tags=["events"])


@router.post("/events", response_model=EventAck)
async def consume_event(
    raw: dict[str, Any], state: LedgerState = Depends(get_state)
) -> EventAck:
    """Consume one event envelope ``{ id, type, ts, data }``.

    Idempotent on ``event.id``: a redelivered event returns ``duplicate`` and
    posts nothing new.
    """
    envelope = parser.parse_envelope(raw)
    result = state.dispatcher.dispatch(envelope)
    return EventAck(
        event_id=result.event_id,
        event_type=result.event_type,
        status=result.status,
        result_id=result.result_id,
    )
