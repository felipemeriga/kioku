"""Journal-entry posting — the ledger's ground-truth accounting logic.

- :func:`build_settlement_entry` — turns a ``payment.settled`` into the balanced
  settlement entry.
- :func:`build_refund_reversal_entry` — turns a ``refund.completed`` into the
  mirror-image reversal entry.

Both call :meth:`JournalEntry.assert_balanced` before returning, so an
unbalanced entry can never leave this module.
"""

from .settlement import build_settlement_entry
from .refund import build_refund_reversal_entry

__all__ = ["build_settlement_entry", "build_refund_reversal_entry"]
