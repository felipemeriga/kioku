import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _sections(purpose):
    from services.folder_summary.briefing_schema import empty_briefing, new_section

    s = empty_briefing()
    s["overview"] = new_section({"purpose": purpose, "description": ""})
    return s


class TestHistoryRoute(unittest.TestCase):
    def tearDown(self):
        from main import app

        app.dependency_overrides.clear()

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
            patch("routes.briefing.list_summaries", return_value=rows) as listing,
        ):
            c = self._client()
            r = c.get("/api/folders/11111111-1111-1111-1111-111111111111/briefing/history")
        assert r.status_code == 200, r.text
        body = r.json()
        self.assertEqual([v["id"] for v in body], ["v2", "v1"])
        self.assertIn("overview", body[0]["changed_sections"])  # v2 changed overview vs v1
        listing.assert_called_once_with(
            sb, "11111111-1111-1111-1111-111111111111", "u1", limit=51, offset=0
        )

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

    def test_restore_reinserts_version_sections(self):
        row = {"id": "v1", "content": {"sections": _sections("A")}}
        sb = MagicMock()
        q = sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value
        q.execute.return_value.data = [row]
        with (
            patch("routes.briefing.get_supabase", return_value=sb),
            patch("routes.briefing._folder_must_be_repo", return_value={"kind": "repo"}),
            patch("routes.briefing._persist_sections") as persist,
        ):
            c = self._client()
            r = c.post("/api/folders/11111111-1111-1111-1111-111111111111/briefing/restore/v1")
        assert r.status_code == 200, r.text
        self.assertEqual(r.json()["restored_from"], "v1")
        # sections handed to _persist_sections are v1's sections
        kw = persist.call_args.kwargs
        self.assertEqual(kw["sections"]["overview"]["content"]["purpose"], "A")
        self.assertEqual(kw.get("trigger"), "restore")
        self.assertEqual(kw["sections"]["overview"]["updated_by"], "u1")
        self.assertEqual(kw["sections"]["overview"]["provenance"], "user_ui")

    def test_history_page_compares_last_result_with_unreturned_predecessor(self):
        rows = [
            {"id": "v3", "content": {"sections": _sections("B")}},
            {"id": "v2", "content": {"sections": _sections("B")}},
            {"id": "v1", "content": {"sections": _sections("A")}},
        ]
        with (
            patch("routes.briefing.get_supabase"),
            patch("routes.briefing._folder_must_be_repo"),
            patch("routes.briefing.list_summaries", return_value=rows),
        ):
            response = self._client().get(
                "/api/folders/11111111-1111-1111-1111-111111111111/briefing/history?limit=2"
            )
        self.assertEqual(response.status_code, 200)
        versions = response.json()
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0]["changed_sections"], [])
        self.assertEqual(versions[1]["changed_sections"], ["overview"])
        self.assertEqual(len(versions[0]["content_hash"]), 64)

    def test_pagination_rejects_invalid_bounds(self):
        client = self._client()
        for query in ("limit=0", "limit=101", "offset=-1"):
            response = client.get(
                f"/api/folders/11111111-1111-1111-1111-111111111111/briefing/history?{query}"
            )
            self.assertEqual(response.status_code, 422)

    def test_history_rejects_non_owner_and_non_repo(self):
        for folder, status in ((None, 404), ({"kind": "folder"}, 400)):
            with (
                patch("routes.briefing.get_supabase"),
                patch("routes.briefing.get_folder", return_value=folder),
            ):
                response = self._client().get(
                    "/api/folders/11111111-1111-1111-1111-111111111111/briefing/history"
                )
            self.assertEqual(response.status_code, status)

    def test_detail_and_restore_reject_missing_or_foreign_version(self):
        sb = MagicMock()
        query = sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.limit.return_value
        query.execute.return_value.data = []
        with (
            patch("routes.briefing.get_supabase", return_value=sb),
            patch("routes.briefing._folder_must_be_repo"),
        ):
            client = self._client()
            for action, method in (("version", client.get), ("restore", client.post)):
                response = method(
                    f"/api/folders/11111111-1111-1111-1111-111111111111/briefing/{action}/foreign"
                )
                self.assertEqual(response.status_code, 404)
        sb.table.return_value.select.return_value.eq.assert_called_with("id", "foreign")
        sb.table.return_value.select.return_value.eq.return_value.eq.assert_called_with(
            "folder_id", "11111111-1111-1111-1111-111111111111"
        )
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.assert_called_with(
            "user_id", "u1"
        )
