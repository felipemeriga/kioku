"""The /chat endpoint must reject a conversation the caller doesn't own."""

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

_CID = "11111111-1111-1111-1111-111111111111"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _sb(rows: list) -> MagicMock:
    sb = MagicMock()
    chain = (
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value
    )
    chain.execute.return_value.data = rows
    return sb


class TestChatOwnership(unittest.TestCase):
    def test_foreign_conversation_is_rejected(self):
        from routes.chat import ChatRequest, chat

        sb = _sb([])  # no conversation owned by this user with that id
        with patch("routes.chat.get_supabase", return_value=sb):
            with self.assertRaises(HTTPException) as ctx:
                _run(chat(ChatRequest(conversation_id=_CID, content="hi"), user_id="u1"))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_owned_conversation_is_allowed(self):
        from routes.chat import ChatRequest, chat

        sb = _sb([{"id": _CID}])  # owned
        with patch("routes.chat.get_supabase", return_value=sb):
            resp = _run(chat(ChatRequest(conversation_id=_CID, content="hi"), user_id="u1"))
        # Owned → returns a StreamingResponse without raising; the generator is
        # lazy, so stream_rag_response isn't invoked during the test.
        self.assertIsNotNone(resp)
