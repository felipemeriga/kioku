import unittest
from unittest.mock import MagicMock


class TestListSummaries(unittest.TestCase):
    def test_orders_desc_and_ranges(self):
        from services.folder_summary.repo import list_summaries

        sb = MagicMock()
        chain = sb.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.range.return_value
        chain.execute.return_value.data = [{"id": "v2"}, {"id": "v1"}]
        out = list_summaries(sb, "f1", "u1", limit=10, offset=0)
        self.assertEqual([r["id"] for r in out], ["v2", "v1"])
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.order.assert_called_with(
            "generated_at", desc=True
        )
        chain_order = sb.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value
        chain_order.range.assert_called_with(0, 9)
