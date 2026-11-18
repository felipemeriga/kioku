"""Unit tests for services.llm — task→model routing, cache markers, singleton."""

import unittest
from unittest.mock import MagicMock, patch


class TestComplete(unittest.TestCase):
    def test_every_task_has_a_subscription_model(self):
        from services.llm import MODEL_FOR_TASK, Task

        for task in Task:
            self.assertTrue(MODEL_FOR_TASK[task])

    def test_complete_passes_actual_owner_to_subscription_facade(self):
        from services.llm import Task, complete
        from services.usage_ledger import UsageAttribution

        value = MagicMock()
        with (
            patch("services.llm.native_completion", return_value=value) as native,
            patch("services.llm.get_client") as api,
        ):
            self.assertIs(
                complete(
                    task=Task.QUERY_REWRITE,
                    messages=[{"role": "user", "content": "question"}],
                    attribution=UsageAttribution(
                        "another-user", "chat", "rewrite", folder_id="folder"
                    ),
                ),
                value,
            )
        scope = native.call_args.kwargs["fallback_scope"]
        self.assertEqual((scope.owner_id, scope.folder_ids), ("another-user", ("folder",)))
        api.assert_not_called()

    def test_failed_subscription_never_calls_api(self):
        from services.ai.client import ExecutionError
        from services.llm import Task, complete

        with (
            patch("services.llm.native_completion", side_effect=ExecutionError("unavailable")),
            patch("services.llm.get_client") as api,
        ):
            with self.assertRaises(ExecutionError):
                complete(
                    task=Task.QUERY_REWRITE, messages=[{"role": "user", "content": "question"}]
                )
        api.assert_not_called()

    def test_deprecated_api_and_sdk_streaming_fail_closed(self):
        from services.ai.client import ExecutionError
        from services.llm import Task, api_only_client, get_client, stream_complete

        for call in (
            get_client,
            lambda: api_only_client(Task.EVAL_JUDGE),
            lambda: stream_complete(task=Task.RAG_AGENT, messages=[]),
        ):
            with self.assertRaises(ExecutionError):
                call()


class TestAgentParams(unittest.TestCase):
    def test_model_and_mode_are_independent(self):
        from services.llm import MODEL_FOR_TASK
        from services.rag import _agent_params

        # model picks the model; only 'deep' enables thinking.
        cases = [
            ("haiku", "plain", "haiku", False),
            ("haiku", "agentic", "haiku", False),
            ("haiku", "deep", "haiku", True),
            ("sonnet", "agentic", "sonnet", False),
            ("sonnet", "deep", "sonnet", True),
        ]
        for model, mode, want_model, want_thinking in cases:
            task, max_tokens, thinking = _agent_params(model, mode)
            self.assertIn(want_model, MODEL_FOR_TASK[task])
            if want_thinking:
                self.assertTrue(thinking and thinking < max_tokens)
            else:
                self.assertIsNone(thinking)

    def test_plain_mode_uses_only_kb_tool(self):
        from services.rag import _mode_config

        _prompt, tools = _mode_config("plain")
        self.assertEqual([t["name"] for t in tools], ["knowledge_base_search"])

    def test_agentic_mode_uses_all_tools(self):
        from services.rag import _mode_config
        from services.tools import TOOL_DEFINITIONS

        _prompt, tools = _mode_config("agentic")
        self.assertEqual(len(tools), len(TOOL_DEFINITIONS))


if __name__ == "__main__":
    unittest.main()
