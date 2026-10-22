import unittest
from unittest.mock import MagicMock, patch

from services.folder_summary.briefing_schema import (
    briefing_content_hash,
    empty_briefing,
    new_section,
)


class TestDedupGate(unittest.TestCase):
    def _sections(self, purpose):
        s = empty_briefing()
        s["overview"] = new_section({"purpose": purpose, "description": ""})
        return s

    def test_identical_content_skips_insert(self):
        from routes.briefing import _persist_sections

        sb = MagicMock()
        sections = self._sections("same")
        latest = {
            "content": {"sections": sections},
            "content_hash": briefing_content_hash(sections),
        }
        with patch("routes.briefing.get_latest_summary", return_value=latest):
            _persist_sections(sb, folder_id="f1", user_id="u1", sections=sections)
        sb.table.return_value.insert.assert_not_called()

    def test_changed_content_inserts_with_hash(self):
        from routes.briefing import _persist_sections

        sb = MagicMock()
        latest = {
            "content": {"sections": self._sections("old")},
            "content_hash": briefing_content_hash(self._sections("old")),
        }
        new = self._sections("new")
        with patch("routes.briefing.get_latest_summary", return_value=latest):
            _persist_sections(sb, folder_id="f1", user_id="u1", sections=new)
        payload = sb.table.return_value.insert.call_args.args[0]
        self.assertEqual(payload["content_hash"], briefing_content_hash(new))

    def test_first_version_always_inserts(self):
        from routes.briefing import _persist_sections

        sb = MagicMock()
        with patch("routes.briefing.get_latest_summary", return_value=None):
            _persist_sections(sb, folder_id="f1", user_id="u1", sections=self._sections("first"))
        sb.table.return_value.insert.assert_called_once()

    def test_legacy_null_hash_computed_on_the_fly(self):
        from routes.briefing import _persist_sections

        sb = MagicMock()
        sections = self._sections("same")
        latest = {"content": {"sections": sections}, "content_hash": None}  # legacy row
        with patch("routes.briefing.get_latest_summary", return_value=latest):
            _persist_sections(sb, folder_id="f1", user_id="u1", sections=sections)
        sb.table.return_value.insert.assert_not_called()  # identical -> still dedup'd
