import unittest

from services.folder_summary.briefing_schema import (
    briefing_content_hash,
    changed_sections,
    empty_briefing,
    new_section,
)


class TestBriefingHash(unittest.TestCase):
    def test_hash_excludes_metadata(self):
        a = empty_briefing()
        a["overview"] = new_section({"purpose": "p", "description": "d"}, updated_by="x")
        b = empty_briefing()
        b["overview"] = new_section({"purpose": "p", "description": "d"}, updated_by="y")
        # same content, different metadata (updated_by/updated_at) -> same hash
        self.assertEqual(briefing_content_hash(a), briefing_content_hash(b))

    def test_hash_changes_with_content(self):
        a = empty_briefing()
        b = empty_briefing()
        b["overview"] = new_section({"purpose": "changed", "description": ""})
        self.assertNotEqual(briefing_content_hash(a), briefing_content_hash(b))

    def test_changed_sections_lists_only_differing_keys(self):
        prev = empty_briefing()
        cur = empty_briefing()
        cur["architecture"] = new_section({"summary": "new", "components": [], "data_flow": ""})
        self.assertEqual(changed_sections(prev, cur), ["architecture"])

    def test_changed_sections_none_prev_lists_nonempty(self):
        cur = empty_briefing()
        cur["overview"] = new_section({"purpose": "p", "description": ""})
        self.assertIn("overview", changed_sections(None, cur))
        self.assertNotIn("preferences", cur)  # retired from new briefings
