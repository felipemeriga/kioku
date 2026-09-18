"""FastAPI application factory + entrypoint for obol-ledger.

Wires the routers, registers exception handlers, and constructs the app-wide
:class:`LedgerState` at startup.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import __version__
from .api import accounts_router, events_router, health_router, payout_batches_router
from .config import get_settings
from .errors import register_exception_handlers
from .state import LedgerState


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Construct long-lived state once, on startup.
    app.state.ledger = LedgerState()
    yield
    # No external resources to tear down (in-memory stores).


def create_app() -> FastAPI:
    """Build and return the configured FastAPI application."""
    app = FastAPI(
        title="Obol Ledger",
        version=__version__,
        summary="Double-entry accounting core for the Obol platform.",
        lifespan=lifespan,
    )

    register_exception_handlers(app)

    app.include_router(health_router)
    app.include_router(events_router)
    app.include_router(accounts_router)
    app.include_router(payout_batches_router)

    return app


app = create_app()


def run() -> None:  # pragma: no cover - thin uvicorn shim
    """Console-script entrypoint (``obol-ledger``)."""
    import uvicorn

    settings = get_settings()
    uvicorn.run("obol_ledger.main:app", host=settings.host, port=settings.port)


if __name__ == "__main__":  # pragma: no cover
    run()
