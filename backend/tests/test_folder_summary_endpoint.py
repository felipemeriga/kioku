from datetime import datetime, timedelta, timezone
import routes.cli as cli
from routes.cli import _needs_generation, _is_uuid


def test_needs_generation_when_no_row():
    assert _needs_generation(None) is True


def test_needs_generation_when_stale():
    old = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    assert _needs_generation(old) is True


def test_fresh_summary_is_not_stale():
    recent = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert _needs_generation(recent) is False


def test_needs_generation_handles_odd_microsecond_precision():
    # Postgres emits fractional seconds with any digit count (e.g. '.4716');
    # a RECENT such timestamp must be treated as fresh, not fall through to True.
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    s = now.strftime("%Y-%m-%dT%H:%M:%S") + ".4716+00:00"
    assert _needs_generation(s) is False


def test_is_uuid_guard():
    # A well-formed UUID passes; anything else must be rejected so it never
    # reaches a uuid DB column (which would raise 22P02 → an uncaught 500).
    assert _is_uuid("00000000-0000-0000-0000-000000000000") is True
    assert _is_uuid("7ce70a5d-9916-42a4-b7a1-e218f5f7cb84") is True
    for bad in ["not-a-uuid", "", "'; DROP TABLE folders;--", "123", None]:
        assert _is_uuid(bad) is False
