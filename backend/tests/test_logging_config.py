import logging

import pytest

from services.logging_config import RoutineAccessFilter, configure_transport_logging


@pytest.mark.parametrize("status,visible", [(200, False), (307, False), (401, True), (500, True)])
def test_polling_errors_remain_visible(status, visible):
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        "%s %s %s %s %s",
        ("client", "POST", "/internal/tsukai/mcp/", "1.1", status),
        None,
    )
    assert RoutineAccessFilter().filter(record) is visible


def test_normal_chat_access_remains_visible():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        "%s %s %s %s %s",
        ("client", "POST", "/api/chat", "1.1", 200),
        None,
    )
    assert RoutineAccessFilter().filter(record)


def test_verbose_transport_opt_in(monkeypatch):
    names = ("httpx", "httpcore", "mcp.server", "uvicorn.access")
    loggers = [logging.getLogger(name) for name in names]
    original = [(logger.level, list(logger.filters)) for logger in loggers]
    try:
        monkeypatch.delenv("KIOKU_VERBOSE_HTTP_LOGS", raising=False)
        configure_transport_logging()
        configure_transport_logging()
        assert all(logger.level == logging.WARNING for logger in loggers[:3])
        assert sum(isinstance(f, RoutineAccessFilter) for f in loggers[3].filters) == 1
        monkeypatch.setenv("KIOKU_VERBOSE_HTTP_LOGS", "true")
        configure_transport_logging()
        assert all(logger.level == logging.INFO for logger in loggers[:3])
        assert not any(isinstance(f, RoutineAccessFilter) for f in loggers[3].filters)
    finally:
        for logger, (level, filters) in zip(loggers, original):
            logger.setLevel(level)
            logger.filters = filters
