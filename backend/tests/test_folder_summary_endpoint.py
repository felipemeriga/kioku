from datetime import datetime, timedelta, timezone
import routes.cli as cli
from routes.cli import _needs_generation


def test_needs_generation_when_no_row():
    assert _needs_generation(None) is True


def test_needs_generation_when_stale():
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    assert _needs_generation(old) is True


def test_fresh_summary_is_not_stale():
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert _needs_generation(recent) is False
