"""Keep routine transport polling out of production application logs."""

import logging
import os


class RoutineAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno >= logging.WARNING:
            return True
        args = record.args
        if not isinstance(args, tuple) or len(args) != 5:
            return True
        _, _, path, _, status = args
        if not isinstance(path, str) or not isinstance(status, int) or status >= 400:
            return True
        path = path.partition("?")[0]
        return not (
            path.startswith("/internal/tsukai/mcp")
            or path in {"/api/health", "/api/usage/native/active-sessions"}
        )


def configure_transport_logging() -> None:
    """Opt into transport diagnostics with KIOKU_VERBOSE_HTTP_LOGS=true."""
    verbose = os.getenv("KIOKU_VERBOSE_HTTP_LOGS", "false").lower() in {"1", "true", "yes"}
    for name in ("httpx", "httpcore", "mcp.server"):
        logging.getLogger(name).setLevel(logging.INFO if verbose else logging.WARNING)
    access = logging.getLogger("uvicorn.access")
    for item in list(access.filters):
        if isinstance(item, RoutineAccessFilter):
            access.removeFilter(item)
    if not verbose:
        access.addFilter(RoutineAccessFilter())
