"""The non-Anthropic (LiteLLM) chat loop: streams text, runs tool calls via the
same execute_tool, and emits a usage event — same SSE contract as the Anthropic
path."""

import json
from types import SimpleNamespace
from unittest.mock import patch


def _tc(index, cid, name, args):
    return SimpleNamespace(index=index, id=cid, function=SimpleNamespace(name=name, arguments=args))


def _chunk(content=None, tool_calls=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choices = (
        []
        if (content is None and tool_calls is None and usage is not None)
        else [SimpleNamespace(delta=delta)]
    )
    return SimpleNamespace(choices=choices, usage=usage)


_TOOLS = [
    {
        "name": "knowledge_base_search",
        "description": "search",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}},
    }
]


def _run(**overrides):
    from services.rag import _run_loop_litellm

    kwargs = dict(
        provider="deepseek",
        model="deepseek-chat",
        api_key="sk-test",
        mode="agentic",
        system_prompt="sys",
        tools=_TOOLS,
        messages=[{"role": "user", "content": "hi"}],
        user_id="u1",
        scope_folder_ids=None,
        scope_filename=None,
        debug_trace=None,
        max_rounds=5,
    )
    kwargs.update(overrides)
    return list(_run_loop_litellm(**kwargs))


class TestLiteLLMLoop:
    def test_tool_call_then_answer(self):
        # Round 1: model asks to call the search tool. Round 2: it answers.
        round1 = [
            _chunk(tool_calls=[_tc(0, "call_1", "knowledge_base_search", '{"query": "x"}')]),
            _chunk(usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20)),
        ]
        round2 = [
            _chunk(content="Here is "),
            _chunk(content="the answer."),
            _chunk(usage=SimpleNamespace(prompt_tokens=150, completion_tokens=30)),
        ]
        streams = [iter(round1), iter(round2)]

        def _fake_completion(**kwargs):
            return streams.pop(0)

        with (
            patch("litellm.completion", side_effect=_fake_completion),
            patch("services.rag.execute_tool", return_value="SEARCH RESULT") as exec_tool,
        ):
            events = _run()

        # execute_tool was invoked for the streamed tool call
        exec_tool.assert_called_once()
        assert exec_tool.call_args.args[0] == "knowledge_base_search"
        assert exec_tool.call_args.args[1] == {"query": "x"}

        kinds = [k for k, _ in events]
        text = "".join(p for k, p in events if k == "text_delta")
        assert text == "Here is the answer."
        assert "usage" in kinds

        usage = json.loads(next(p for k, p in events if k == "usage"))
        assert usage["input_tokens"] == 250  # 100 + 150 summed across rounds
        assert usage["output_tokens"] == 50
        assert usage["model"] == "deepseek-chat"

    def test_direct_answer_no_tools(self):
        round1 = [
            _chunk(content="Quick answer."),
            _chunk(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5)),
        ]
        with (
            patch("litellm.completion", side_effect=lambda **k: iter(round1)),
            patch("services.rag.execute_tool") as exec_tool,
        ):
            events = _run()
        exec_tool.assert_not_called()
        assert "".join(p for k, p in events if k == "text_delta") == "Quick answer."
