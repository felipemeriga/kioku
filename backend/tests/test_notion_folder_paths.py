import unittest
from unittest.mock import MagicMock

from services.notion_sync.folder_paths import ensure_notion_folder_path


class TestEnsureNotionFolderPath(unittest.TestCase):
    def test_creates_notion_root_subfolder_and_chain(self):
        # Nothing exists; every get_or_create must insert.
        sb = MagicMock()
        select_chain = sb.table.return_value.select.return_value.eq.return_value.eq.return_value
        select_chain.execute.return_value.data = []

        created: list[dict] = []

        def insert_side_effect(rec):
            created.append(rec)
            fake = MagicMock()
            fake.execute.return_value.data = [{"id": f"fid-{len(created)}", **rec}]
            return fake

        sb.table.return_value.insert.side_effect = insert_side_effect

        leaf_id, parent_path = ensure_notion_folder_path(
            sb,
            user_id="u1",
            root_folder_id="root-1",
            ancestor_titles=["Cosm", "Sprint planning"],
        )

        # Three inserts in order: notion/, Cosm/, Sprint planning/
        self.assertEqual(len(created), 3)
        self.assertEqual(created[0]["name"], "notion")
        self.assertEqual(created[0]["parent_id"], "root-1")
        self.assertEqual(created[1]["name"], "Cosm")
        self.assertEqual(created[1]["parent_id"], "fid-1")
        self.assertEqual(created[2]["name"], "Sprint planning")
        self.assertEqual(created[2]["parent_id"], "fid-2")
        self.assertEqual(leaf_id, "fid-3")
        self.assertEqual(parent_path, "Cosm / Sprint planning")

    def test_reuses_existing_folders(self):
        existing_rows = {
            ("root-1", "notion"): {"id": "existing-notion"},
            ("existing-notion", "Cosm"): {"id": "existing-cosm"},
        }

        def build_select_chain(parent_id_value, name_value):
            fake = MagicMock()
            row = existing_rows.get((parent_id_value, name_value))
            fake.execute.return_value.data = [row] if row else []
            return fake

        # supabase.table("folders").select("id") returns a chain that captures
        # the eq() calls; we simulate by intercepting the chain.
        def table_mock(name):
            table = MagicMock()

            def select(_cols):
                stage = MagicMock()

                def eq_parent(field, parent_val):
                    assert field == "parent_id"
                    stage2 = MagicMock()

                    def eq_name(field2, name_val):
                        assert field2 == "name"
                        return build_select_chain(parent_val, name_val)

                    stage2.eq.side_effect = eq_name
                    return stage2

                stage.eq.side_effect = eq_parent
                return stage

            table.select.side_effect = select

            def insert(rec):
                fake = MagicMock()
                fake.execute.return_value.data = [{"id": "new-sp", **rec}]
                return fake

            table.insert.side_effect = insert
            return table

        sb = MagicMock()
        sb.table.side_effect = table_mock

        leaf_id, parent_path = ensure_notion_folder_path(
            sb,
            user_id="u1",
            root_folder_id="root-1",
            ancestor_titles=["Cosm", "Sprint planning"],
        )
        self.assertEqual(leaf_id, "new-sp")
        self.assertEqual(parent_path, "Cosm / Sprint planning")

    def test_empty_chain_returns_notion_root(self):
        sb = MagicMock()
        select_chain = sb.table.return_value.select.return_value.eq.return_value.eq.return_value
        select_chain.execute.return_value.data = []
        sb.table.return_value.insert.return_value.execute.return_value.data = [{"id": "notion-fid"}]

        leaf_id, parent_path = ensure_notion_folder_path(
            sb,
            user_id="u1",
            root_folder_id="root-1",
            ancestor_titles=[],
        )
        self.assertEqual(leaf_id, "notion-fid")
        self.assertEqual(parent_path, "")
