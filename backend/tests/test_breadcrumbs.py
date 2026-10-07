import asyncio
from unittest.mock import MagicMock, patch


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_malformed_uuid_returns_empty_without_db():
    from routes.folders import get_breadcrumbs

    sb = MagicMock()
    with patch("routes.folders.get_supabase", return_value=sb, create=True):
        result = _run(get_breadcrumbs("not-a-uuid", user_id="u1"))
    assert result == []
    sb.rpc.assert_not_called()


def test_breadcrumbs_single_rpc_call_preserves_order_and_kind():
    from routes.folders import get_breadcrumbs

    # RPC returns root-first; route maps 1:1, kind falls back to 'folder'.
    rows = [
        {"id": "11111111-1111-1111-1111-111111111111", "name": "Work", "kind": "folder"},
        {"id": "22222222-2222-2222-2222-222222222222", "name": "kioku", "kind": "repo"},
        {"id": "33333333-3333-3333-3333-333333333333", "name": "backend", "kind": None},
    ]
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = rows

    with patch("routes.folders.get_supabase", return_value=sb, create=True):
        result = _run(get_breadcrumbs("33333333-3333-3333-3333-333333333333", user_id="u1"))

    # Exactly one DB round-trip, to the recursive-CTE function.
    sb.rpc.assert_called_once()
    name, payload = sb.rpc.call_args.args
    assert name == "folder_breadcrumbs"
    assert payload == {
        "p_folder_id": "33333333-3333-3333-3333-333333333333",
        "p_user_id": "u1",
    }
    assert [b["name"] for b in result] == ["Work", "kioku", "backend"]
    assert [b["kind"] for b in result] == ["folder", "repo", "folder"]


def test_breadcrumbs_empty_when_rpc_returns_none():
    from routes.folders import get_breadcrumbs

    sb = MagicMock()
    sb.rpc.return_value.execute.return_value.data = None
    with patch("routes.folders.get_supabase", return_value=sb, create=True):
        result = _run(get_breadcrumbs("33333333-3333-3333-3333-333333333333", user_id="u1"))
    assert result == []
