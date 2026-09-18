"""The :class:`JournalEntry` — an immutable, balanced set of journal lines."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field

from ..errors import UnbalancedEntryError
from ..ids import journal_id
from ..money import Money, sum_money
from .journal_line import JournalLine, Side


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JournalEntry(BaseModel):
    """A balanced accounting transaction: 2+ lines whose debits equal credits.

    Entries are append-only and never mutated. A refund does not edit the
    original settlement entry — it posts a new, opposite entry that references
    it via ``reverses``.
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=journal_id)
    event_id: str = Field(..., description="The source event.id that produced this entry.")
    kind: str = Field(..., description="Semantic kind, e.g. 'settlement' or 'refund_reversal'.")
    currency: str = Field(..., min_length=3, max_length=3)
    lines: list[JournalLine] = Field(..., min_length=2)
    reverses: str | None = Field(
        default=None, description="If a reversal, the journal id it mirrors."
    )
    reference: dict[str, str] = Field(
        default_factory=dict, description="Business refs, e.g. {'charge_id': 'chg_0001'}."
    )
    created_at: datetime = Field(default_factory=_utcnow)

    # -- invariant ------------------------------------------------------------

    def total_debits(self) -> Money:
        return sum_money(
            [ln.amount for ln in self.lines if ln.side is Side.DEBIT], self.currency
        )

    def total_credits(self) -> Money:
        return sum_money(
            [ln.amount for ln in self.lines if ln.side is Side.CREDIT], self.currency
        )

    def is_balanced(self) -> bool:
        return self.total_debits() == self.total_credits()

    def assert_balanced(self) -> "JournalEntry":
        """Raise :class:`UnbalancedEntryError` unless debits == credits.

        This is the ledger's hard invariant. Posting code calls it before an
        entry is ever handed to the repository.
        """
        debits, credits = self.total_debits(), self.total_credits()
        if debits != credits:
            raise UnbalancedEntryError(
                "journal entry does not balance",
                detail={
                    "event_id": self.event_id,
                    "kind": self.kind,
                    "total_debits": debits.amount_minor,
                    "total_credits": credits.amount_minor,
                    "currency": self.currency,
                },
            )
        return self
