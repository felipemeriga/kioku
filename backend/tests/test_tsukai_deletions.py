from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx

from services.ai.deletions import reconcile_deletions


def test_failing_deletion_does_not_abort_later_intent_and_retry_order_advances():
    rows = [
        {"id": "bad", "owner_id": "owner", "kind": "account"},
        {"id": "good", "owner_id": "owner", "kind": "account"},
    ]
    changes, ordering = {}, []

    class Query:
        def __init__(self, table):
            self.table, self.values, self.row = table, None, None

        def select(self, *args):
            return self

        def in_(self, *args):
            return self

        def order(self, key):
            ordering.append(key)
            return self

        def limit(self, *args):
            return self

        def delete(self):
            return self

        def lt(self, *args):
            return self

        def eq(self, key, value):
            if key == "id":
                self.row = value
            return self

        def update(self, values):
            self.values = values
            return self

        def execute(self):
            if self.values:
                changes.setdefault(self.row, {}).update(self.values)
            return SimpleNamespace(
                data=rows if self.table == "tsukai_domain_deletions" and not self.values else []
            )

    class Database:
        def table(self, name):
            return Query(name)

    bad, good = MagicMock(), MagicMock()
    bad.delete_domain.side_effect = httpx.ConnectError("offline")
    good.delete_domain.return_value = {"tombstone_id": "cleaned", "status": "cleaned"}
    with (
        patch("services.ai.deletions.get_supabase_thread_safe", return_value=Database()),
        patch("services.ai.deletions.client_for", side_effect=[bad, good]),
    ):
        reconcile_deletions()
    assert ordering == ["last_attempt_at"]
    assert "last_attempt_at" in changes["bad"]
    assert changes["good"]["state"] == "cleaned"
    bad.close.assert_called_once()
    good.close.assert_called_once()
