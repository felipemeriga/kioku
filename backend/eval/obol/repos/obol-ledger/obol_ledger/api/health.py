"""Health + readiness endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import __version__
from ..state import LedgerState, get_state

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe."""
    return {"status": "ok", "service": "obol-ledger", "version": __version__}


@router.get("/readyz")
async def readyz(state: LedgerState = Depends(get_state)) -> dict[str, object]:
    """Readiness probe with a quick ledger integrity summary."""
    entries = state.journal.all()
    unbalanced = [e.id for e in entries if not e.is_balanced()]
    return {
        "status": "ok" if not unbalanced else "degraded",
        "journal_entries": len(entries),
        "unbalanced_entries": unbalanced,
        "gateway_url": state.settings.gateway_url,
    }
