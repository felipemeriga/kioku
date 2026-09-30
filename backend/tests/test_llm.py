"""Unit tests for services.llm — task→model routing, cache markers, singleton."""

import unittest
from unittest.mock import MagicMock, patch


class TestComplete(unittest.TestCase):
    """Verify complete() builds the right kwargs and routes by task."""

    def _patched_client(self):
        mock_client = MagicMock()
        mock_client.messages.create.return_value = MagicMock(content=[])
        return mock_client

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

    def test_thinking_budget_enables_thinking_and_beta_header(self):
        from services.llm import Task, complete

        mock_client = self._patched_client()
        with patch("services.llm.get_client", return_value=mock_client):
            complete(
                task=Task.RAG_AGENT_DEEP,
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=8192,
                thinking_budget=2048,
            )

        call_kwargs = mock_client.messages.create.call_args.kwargs
        self.assertEqual(call_kwargs["thinking"], {"type": "enabled", "budget_tokens": 2048})
        self.assertIn("anthropic-beta", call_kwargs["extra_headers"])

    def test_no_thinking_budget_means_no_thinking_kwarg(self):
        from services.llm import Task, complete

        mock_client = self._patched_client()
        with patch("services.llm.get_client", return_value=mock_client):
            complete(task=Task.RAG_AGENT, messages=[{"role": "user", "content": "hi"}])

        call_kwargs = mock_client.messages.create.call_args.kwargs
        self.assertNotIn("thinking", call_kwargs)
        self.assertNotIn("extra_headers", call_kwargs)


class TestAgentParams(unittest.TestCase):
    def test_fast_mode_is_haiku_no_thinking(self):
        from services.llm import MODEL_FOR_TASK
        from services.rag import _agent_params

        task, max_tokens, thinking = _agent_params(fast_mode=True)
        self.assertIn("haiku", MODEL_FOR_TASK[task])
        self.assertIsNone(thinking)

    def test_full_mode_is_deep_with_thinking(self):
        from services.llm import MODEL_FOR_TASK
        from services.rag import _agent_params

        task, max_tokens, thinking = _agent_params(fast_mode=False)
        self.assertIn("sonnet", MODEL_FOR_TASK[task])
        self.assertTrue(thinking and thinking < max_tokens)


if __name__ == "__main__":
    unittest.main()
