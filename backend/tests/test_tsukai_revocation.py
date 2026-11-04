from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from services.ai.chat import reconcile_pending


def test_scope_revocation_terminalizes_poison_batch_and_does_not_starve_next_healthy_turn():
    turns = [
        {"id": str(index), "owner_id": "owner", "state": "submitted", "job_id": f"job-{index}"}
        for index in range(101)
    ]
    healthy = []

    class Query:
        def __init__(self):
            self.filters = {}
            self.changes = None

        def select(self, *args):
            return self

        def in_(self, *args):
            return self

        def order(self, *args):
            return self

        def limit(self, *args):
            return self

        def eq(self, key, value):
            self.filters[key] = value
            return self

        def update(self, values):
            self.changes = values
            return self

        def execute(self):
            if self.changes:
                for turn in turns:
                    if turn["id"] == self.filters["id"]:
                        turn.update(self.changes)
                return SimpleNamespace(data=[])
            return SimpleNamespace(
                data=[
                    dict(turn)
                    for turn in turns
                    if turn["state"] in {"prepared", "submitted", "committed"}
                ][:100]
            )

    class Database:
        def table(self, *args):
            return Query()

    def reconcile(turn):
        if turn["id"] != "100":
            raise HTTPException(403, "Execution scope changed")
        healthy.append(turn["id"])

    with (
        patch("services.ai.chat.get_supabase_thread_safe", return_value=Database()),
        patch("services.ai.chat.reconcile_turn", side_effect=reconcile),
    ):
        reconcile_pending()
        assert all(
            turn["state"] == "failed" and turn["error_code"] == "scope_revoked"
            for turn in turns[:100]
        )
        assert all(turn["cancel_requested"] for turn in turns[:100])
        reconcile_pending()
    assert healthy == ["100"]
