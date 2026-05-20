"""Unit tests for services.llm — task→model routing, cache markers, singleton."""

import unittest
from unittest.mock import MagicMock, patch


class TestComplete(unittest.TestCase):
    """Verify complete() builds the right kwargs and routes by task."""

    def _patched_client(self):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(content=[])
        return mock_client

    def test_task_routes_to_correct_model(self):
        from services.llm import Task, complete

        mock_client = self._patched_client()
        with patch("services.llm.get_client", return_value=mock_client):
            complete(task=Task.METADATA, messages=[{"role": "user", "content": "hi"}])

        call_kwargs = mock_client.messages.create.call_args.kwargs
        self.assertEqual(call_kwargs["model"], "claude-haiku-4-5-20251001")

    def test_every_task_has_a_model(self):
        from services.llm import MODEL_FOR_TASK, Task

        for task in Task:
            self.assertIn(task, MODEL_FOR_TASK, f"{task} missing from MODEL_FOR_TASK")
            self.assertTrue(MODEL_FOR_TASK[task], f"{task} maps to empty model string")

    def test_cache_system_true_wraps_system_as_block_with_cache_control(self):
        from services.llm import Task, complete

        mock_client = self._patched_client()
        with patch("services.llm.get_client", return_value=mock_client):
            complete(
                task=Task.METADATA,
                messages=[{"role": "user", "content": "hi"}],
                system="be helpful",
            )

        call_kwargs = mock_client.messages.create.call_args.kwargs
        self.assertEqual(
            call_kwargs["system"],
            [{"type": "text", "text": "be helpful", "cache_control": {"type": "ephemeral"}}],
        )

    def test_cache_system_false_passes_system_as_string(self):
        from services.llm import Task, complete

        mock_client = self._patched_client()
        with patch("services.llm.get_client", return_value=mock_client):
            complete(
                task=Task.METADATA,
                messages=[{"role": "user", "content": "hi"}],
                system="be helpful",
                cache_system=False,
            )

        call_kwargs = mock_client.messages.create.call_args.kwargs
        self.assertEqual(call_kwargs["system"], "be helpful")

    def test_no_system_means_no_system_kwarg(self):
        from services.llm import Task, complete

        mock_client = self._patched_client()
        with patch("services.llm.get_client", return_value=mock_client):
            complete(task=Task.METADATA, messages=[{"role": "user", "content": "hi"}])

        call_kwargs = mock_client.messages.create.call_args.kwargs
        self.assertNotIn("system", call_kwargs)

    def test_cache_system_true_marks_last_tool(self):
        from services.llm import Task, complete

        tools = [
            {"name": "a", "description": "a", "input_schema": {}},
            {"name": "b", "description": "b", "input_schema": {}},
        ]
        mock_client = self._patched_client()
        with patch("services.llm.get_client", return_value=mock_client):
            complete(
                task=Task.RAG_AGENT,
                messages=[{"role": "user", "content": "hi"}],
                tools=tools,
            )

        call_kwargs = mock_client.messages.create.call_args.kwargs
        sent_tools = call_kwargs["tools"]
        self.assertNotIn("cache_control", sent_tools[0])
        self.assertEqual(sent_tools[1]["cache_control"], {"type": "ephemeral"})

    def test_cache_system_false_leaves_tools_unchanged(self):
        from services.llm import Task, complete

        tools = [{"name": "a", "description": "a", "input_schema": {}}]
        mock_client = self._patched_client()
        with patch("services.llm.get_client", return_value=mock_client):
            complete(
                task=Task.RAG_AGENT,
                messages=[{"role": "user", "content": "hi"}],
                tools=tools,
                cache_system=False,
            )

        call_kwargs = mock_client.messages.create.call_args.kwargs
        self.assertNotIn("cache_control", call_kwargs["tools"][0])

    def test_max_tokens_is_passed_through(self):
        from services.llm import Task, complete

        mock_client = self._patched_client()
        with patch("services.llm.get_client", return_value=mock_client):
            complete(
                task=Task.METADATA,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=4096,
            )

        self.assertEqual(mock_client.messages.create.call_args.kwargs["max_tokens"], 4096)


class TestGetClient(unittest.TestCase):
    """Verify get_client() returns a singleton."""

    def test_get_client_is_singleton(self):
        from services.llm import get_client

        get_client.cache_clear()
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}):
            client_a = get_client()
            client_b = get_client()
        self.assertIs(client_a, client_b)


if __name__ == "__main__":
    unittest.main()
