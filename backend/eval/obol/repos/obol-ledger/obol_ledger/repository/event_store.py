"""Idempotency ledger for processed events.

Consumers must be idempotent on ``event.id`` (SPEC "Events"). This store
records which event ids have already been applied and what they produced, so a
redelivered event is a no-op that returns the original result.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessedEvent:
    """Record of an already-applied event."""

    event_id: str
    event_type: str
    #: Journal id produced (settlement/reversal) or batch id (payout), if any.
    result_id: str | None


class ProcessedEventStore:
    """Tracks applied event ids for idempotent consumption."""

    def __init__(self) -> None:
        self._seen: dict[str, ProcessedEvent] = {}

    def is_processed(self, event_id: str) -> bool:
        return event_id in self._seen

    def get(self, event_id: str) -> ProcessedEvent | None:
        return self._seen.get(event_id)

    def record(
        self, event_id: str, event_type: str, result_id: str | None
    ) -> ProcessedEvent:
        record = ProcessedEvent(event_id=event_id, event_type=event_type, result_id=result_id)
        self._seen[event_id] = record
        return record
