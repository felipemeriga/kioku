import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _sections(purpose):
    from services.folder_summary.briefing_schema import empty_briefing, new_section

    s = empty_briefing()
    s["overview"] = new_section({"purpose": purpose, "description": ""})
    return s


class TestHistoryRoute(unittest.TestCase):
    def _client(self):
        from auth import get_current_user
        from main import app

        app.dependency_overrides[get_current_user] = lambda: "u1"
        return TestClient(app)

    def test_history_lists_changed_sections_newest_first(self):
        rows = [
            {
                "id": "v2",
                "generated_at": "2026-10-22T02:00:00Z",
                "trigger": "edit",
                "content": {"sections": _sections("B")},
                "sections": _sections("B"),
                "content_hash": "h2",
            },
            {
                "id": "v1",
                "generated_at": "2026-10-22T01:00:00Z",
                "trigger": "edit",
                "content": {"sections": _sections("A")},
                "sections": _sections("A"),
                "content_hash": "h1",
            },
        ]
        sb = MagicMock()
        with (
            patch("routes.briefing.get_supabase", return_value=sb),
            patch("routes.briefing._folder_must_be_repo", return_value={"kind": "repo"}),
            patch("routes.briefing.list_summaries", return_value=rows),
        ):
            c = self._client()
            r = c.get("/api/folders/11111111-1111-1111-1111-111111111111/briefing/history")
        assert r.status_code == 200, r.text
        body = r.json()
        self.assertEqual([v["id"] for v in body], ["v2", "v1"])
        self.assertIn("overview", body[0]["changed_sections"])  # v2 changed overview vs v1

    def test_version_detail_returns_sections(self):
        row = {
            "id": "v1",
            "generated_at": "t",
            "trigger": "edit",
            "updated_by": "u1",
            "content": {"sections": _sections("A")},
        }
        sb = MagicMock()
        q = sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value
        q.execute.return_value.data = [row]
        with (
            patch("routes.briefing.get_supabase", return_value=sb),
            patch("routes.briefing._folder_must_be_repo", return_value={"kind": "repo"}),
        ):
            c = self._client()
            r = c.get("/api/folders/11111111-1111-1111-1111-111111111111/briefing/version/v1")
        assert r.status_code == 200, r.text
        self.assertEqual(r.json()["sections"]["overview"]["content"]["purpose"], "A")
