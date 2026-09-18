"""Parse inbound event envelopes and their typed ``data`` payloads.

Parsing is separated from dispatch so both the HTTP layer and tests can validate
shapes without side effects. Validation failures raise
:class:`EventValidationError`.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from ..errors import EventValidationError
from ..models.event import (
    EventEnvelope,
    PaymentSettledData,
    PayoutPaidData,
    RefundCompletedData,
)


def parse_envelope(raw: dict[str, Any]) -> EventEnvelope:
    try:
        return EventEnvelope.model_validate(raw)
    except ValidationError as exc:
        raise EventValidationError("invalid event envelope", detail={"errors": exc.errors()}) from exc


def parse_settled(envelope: EventEnvelope) -> PaymentSettledData:
    return _parse_data(envelope, PaymentSettledData)


def parse_refund(envelope: EventEnvelope) -> RefundCompletedData:
    return _parse_data(envelope, RefundCompletedData)


def parse_payout_paid(envelope: EventEnvelope) -> PayoutPaidData:
    return _parse_data(envelope, PayoutPaidData)


def _parse_data(envelope: EventEnvelope, model: type) -> Any:
    try:
        return model.model_validate(envelope.data)
    except ValidationError as exc:
        raise EventValidationError(
            f"invalid data for event type {envelope.type!r}",
            detail={"event_id": envelope.id, "errors": exc.errors()},
        ) from exc
