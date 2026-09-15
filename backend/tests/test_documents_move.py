import asyncio
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _sb(notion_rows: list) -> MagicMock:
    sb = MagicMock()
    notion_check = (
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value
    )
    notion_check.limit.return_value.execute.return_value.data = notion_rows
    return sb


class TestMoveDocument(unittest.TestCase):
    def test_notion_synced_document_cannot_be_moved(self):
        from routes.documents import MoveDocumentRequest, move_document

        sb = _sb(notion_rows=[{"id": "chunk-1"}])
        with patch("routes.documents.get_supabase", return_value=sb):
            with self.assertRaises(HTTPException) as ctx:
                _run(
                    move_document(
                        "Cosm Page.md",
                        MoveDocumentRequest(folder_id=None),
                        user_id="u1",
                    )
                )
        self.assertEqual(ctx.exception.status_code, 400)
        sb.table.return_value.update.assert_not_called()

    def test_regular_document_moves(self):
        from routes.documents import MoveDocumentRequest, move_document

        sb = _sb(notion_rows=[])
        with patch("routes.documents.get_supabase", return_value=sb):
            result = _run(
                move_document(
                    "notes.pdf",
                    MoveDocumentRequest(folder_id=None),
                    user_id="u1",
                )
            )
        self.assertEqual(result, {"ok": True})
        update_args = sb.table.return_value.update.call_args.args[0]
        self.assertEqual(update_args["folder_id"], None)
