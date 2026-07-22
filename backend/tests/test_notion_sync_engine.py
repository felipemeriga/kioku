import unittest
from datetime import datetime, timedelta, timezone


def _cfg(**kw):
    base = {
        "id": "cfg-1",
        "user_id": "u1",
        "root_folder_id": "root-1",
        "notion_page_id": "cosm",
        "integration_token_encrypted": "encrypted",
        "fast_poll_interval_min": 5,
        "full_reconciliation_interval_hours": 24,
        "last_fast_sync_at": None,
        "last_full_sync_at": None,
    }
    base.update(kw)
    return base


class TestSyncLoopSchedules(unittest.TestCase):
    def test_only_returns_configs_whose_intervals_elapsed(self):
        from services.notion_sync.sync_engine import _configs_due_for_fast_poll

        now = datetime.now(timezone.utc)
        due = _cfg(
            id="a",
            last_fast_sync_at=(now - timedelta(minutes=10)).isoformat(),
            fast_poll_interval_min=5,
        )
        not_due = _cfg(
            id="b",
            last_fast_sync_at=(now - timedelta(minutes=1)).isoformat(),
            fast_poll_interval_min=5,
        )
        never = _cfg(id="c", last_fast_sync_at=None, fast_poll_interval_min=5)

        result = _configs_due_for_fast_poll([due, not_due, never], now=now)
        self.assertEqual({c["id"] for c in result}, {"a", "c"})
