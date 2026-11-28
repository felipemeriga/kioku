import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from jsonschema import validate
from langchain_core.prompt_values import StringPromptValue
from ragas.metrics._answer_relevance import ResponseRelevancePrompt
from ragas.metrics._context_precision import ContextPrecisionPrompt
from ragas.metrics._context_recall import ContextRecallClassificationPrompt
from ragas.metrics._faithfulness import NLIStatementPrompt, StatementGeneratorPrompt
from ragas.prompt.pydantic_prompt import extract_json

from services.ai import evaluation
from services.ai.client import ExecutionError
from services.ai.contracts import completion_schema, completion_text
from services.ai.scope import ExecutionScope, current_scope


@pytest.mark.parametrize(
    "prompt_type, output",
    [
        (StatementGeneratorPrompt, {"statements": ["A claim"]}),
        (
            NLIStatementPrompt,
            {"statements": [{"statement": "A claim", "reason": "Source", "verdict": 1}]},
        ),
        (ResponseRelevancePrompt, {"question": "What claim?", "noncommittal": 0}),
        (ContextPrecisionPrompt, {"reason": "Source", "verdict": 1}),
        (
            ContextRecallClassificationPrompt,
            {"classifications": [{"statement": "A claim", "reason": "Source", "attributed": 1}]},
        ),
    ],
)
def test_each_ragas_prompt_has_a_registered_typed_envelope(prompt_type, output):
    schema = evaluation._judge_schema(prompt_type().to_string())
    envelope = {
        "schema_version": 1,
        "outcome": "completed",
        "data": {"value": output},
        "missing_inputs": [],
        "failure": None,
        "warnings": [],
    }
    validate(envelope, completion_schema("eval_judge", judge_schema=schema))
    assert json.loads(completion_text("eval_judge", envelope, judge_schema=schema)) == output

    invalid = {**envelope, "data": {"value": {**output, "other": "unknown field"}}}
    with pytest.raises(ExecutionError, match="invalid_completion_envelope"):
        completion_text("eval_judge", invalid, judge_schema=schema)

    with pytest.raises(ExecutionError, match="unsupported_judge_schema"):
        completion_schema("query_rewrite", judge_schema=schema)


def test_typed_judge_preserves_relevancy_votes_and_owner_scope(monkeypatch):
    scope = ExecutionScope("owner", ("folder",))
    content = ResponseRelevancePrompt().to_string()
    questions = ["Where is [this?", "What's a } token?", 'How is \\"JSON\\" read?']
    result = [{"question": question, "noncommittal": 0} for question in questions]
    seen = []

    def complete(**request):
        assert current_scope() == scope
        seen.append(request)
        return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(result[len(seen) - 1]))])

    monkeypatch.setattr(evaluation, "native_completion", complete)
    judge = evaluation.SubscriptionJudge(scope)
    out = judge.generate_text(StringPromptValue(text=content), n=3)

    assert len(seen) == 3
    assert all(request["judge_schema"]["title"] == "ResponseRelevanceOutput" for request in seen)
    assert all(request["max_tokens"] == 2048 for request in seen)
    assert [
        json.loads(extract_json(generation.text)) for generation in out.generations[0]
    ] == result


def test_schema_from_retrieved_input_or_modified_signature_is_rejected(monkeypatch):
    complete = Mock()
    monkeypatch.setattr(evaluation, "native_completion", complete)
    judge = evaluation.SubscriptionJudge(ExecutionScope("owner"))
    prompt = ResponseRelevancePrompt().to_string()

    for untrusted in (
        "\nNow perform the same with the following input\n" + prompt,
        prompt.replace(
            '"noncommittal": {"title": "Noncommittal", "type": "integer"}',
            '"noncommittal": {"title": "Noncommittal", "type": "string"}',
        ),
    ):
        assert untrusted != prompt
        with pytest.raises(ExecutionError, match="unsupported_ragas_judge_schema"):
            judge.generate_text(StringPromptValue(text=untrusted))
    complete.assert_not_called()


def test_nli_batches_keep_full_context_order_and_repeated_statement_identity(monkeypatch):
    from ragas.metrics._faithfulness import NLIStatementInput

    context = "Full source containing [brackets] and a } in a string."
    claims = [f"claim {i}" for i in range(18)] + ["claim 0"]
    batches = []

    def complete(**request):
        content = request["messages"][0]["content"]
        data = json.loads(content.rsplit("\ninput: ", 1)[1].removesuffix("\nOutput: "))
        assert data["context"] == context
        statements = data["statements"]
        batches.append(statements)
        schema = request["judge_schema"]["properties"]["statements"]
        assert schema["minItems"] == schema["maxItems"] == len(statements)
        return SimpleNamespace(
            content=[
                SimpleNamespace(
                    text=json.dumps(
                        {
                            "statements": [
                                {"statement": s, "reason": "No match", "verdict": 0}
                                for s in statements
                            ]
                        }
                    )
                )
            ]
        )

    monkeypatch.setattr(evaluation, "native_completion", complete)
    prompt = NLIStatementPrompt().to_string(NLIStatementInput(context=context, statements=claims))
    result = evaluation.SubscriptionJudge(ExecutionScope("owner")).generate_text(
        StringPromptValue(text=prompt)
    )
    scores = json.loads(extract_json(result.generations[0][0].text))["statements"]
    assert [len(batch) for batch in batches] == [8, 8, 3]
    assert [row["statement"] for row in scores] == claims


@pytest.mark.parametrize("statements", [["First"], ["Second", "First"], ["First", "First"]])
def test_nli_rejects_missing_reordered_or_duplicate_verdicts(monkeypatch, statements):
    from ragas.metrics._faithfulness import NLIStatementInput

    monkeypatch.setattr(
        evaluation,
        "native_completion",
        Mock(
            return_value=SimpleNamespace(
                content=[
                    SimpleNamespace(
                        text=json.dumps(
                            {
                                "statements": [
                                    {"statement": s, "reason": "Evidence", "verdict": 1}
                                    for s in statements
                                ]
                            }
                        )
                    )
                ]
            )
        ),
    )
    prompt = NLIStatementPrompt().to_string(
        NLIStatementInput(context="Evidence", statements=["First", "Second"])
    )
    with pytest.raises(ExecutionError, match="incomplete_ragas_nli_verdicts"):
        evaluation.SubscriptionJudge(ExecutionScope("owner")).generate_text(
            StringPromptValue(text=prompt)
        )
