import asyncio
from unittest.mock import MagicMock, patch


def test_document_listing_keeps_original_and_updated_dates():
    from routes.documents import list_documents

    rows = [{"source_filename": "spec.md", "created_at": "2025-01-01T00:00:00Z", "last_updated": "2026-10-24T00:00:00Z"}]
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = rows
    with patch("routes.documents.get_supabase", return_value=sb):
        result = asyncio.run(list_documents(folder_id=None, user_id="user"))
    assert result == rows
    sb.rpc.assert_called_once_with("list_documents_grouped_v2", {"p_user_id": "user", "p_folder_id": None})
