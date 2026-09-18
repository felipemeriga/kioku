"""Append-only store of journal entries and their lines.

The journal is immutable: entries are appended and never updated or deleted.
Reversals are new entries that reference the original via ``reverses``.
"""

from __future__ import annotations

from ..models.journal_entry import JournalEntry
from ..models.journal_line import JournalLine


class JournalStore:
    """In-memory append-only journal."""

    def __init__(self) -> None:
        self._entries: list[JournalEntry] = []
        self._by_id: dict[str, JournalEntry] = {}
        # Fast lookup of the settlement entry for a charge, for refund reversal.
        self._settlement_by_charge: dict[str, str] = {}

    def append(self, entry: JournalEntry) -> JournalEntry:
        """Append a balanced entry. Re-asserts the invariant defensively."""
        entry.assert_balanced()
        self._entries.append(entry)
        self._by_id[entry.id] = entry
        if entry.kind == "settlement":
            charge_id = entry.reference.get("charge_id")
            if charge_id:
                self._settlement_by_charge[charge_id] = entry.id
        return entry

    def get(self, journal_id: str) -> JournalEntry | None:
        return self._by_id.get(journal_id)

    def settlement_for_charge(self, charge_id: str) -> JournalEntry | None:
        jid = self._settlement_by_charge.get(charge_id)
        return self._by_id.get(jid) if jid else None

    def all(self) -> list[JournalEntry]:
        return list(self._entries)

    def lines_for_account(self, account: str) -> list[tuple[JournalEntry, JournalLine]]:
        """Every (entry, line) pair posting to ``account``, in append order."""
        out: list[tuple[JournalEntry, JournalLine]] = []
        for entry in self._entries:
            for line in entry.lines:
                if line.account == account:
                    out.append((entry, line))
        return out

    def __len__(self) -> int:
        return len(self._entries)
