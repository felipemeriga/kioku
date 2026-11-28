"""A judgment cannot simultaneously report failure and no offending claims."""

import json
from types import SimpleNamespace

import pytest
from jsonschema import ValidationError, validate

from eval.obol import answer_eval


@pytest.mark.parametrize(
    "criterion, issues", [("grounded", "unsupported"), ("consistent", "problems")]
)
def test_judge_failure_requires_an_actual_reason(monkeypatch, criterion, issues):
    requests = []

    def complete(**request):
        requests.append(request)
        return SimpleNamespace(
            content=[SimpleNamespace(text=json.dumps({criterion: True, issues: []}))]
        )

    monkeypatch.setattr(answer_eval, "native_completion", complete)
    verdict = answer_eval._judge(
        "Check the answer", "question", "context", "answer", criterion=criterion, reference="gold"
    )
    assert verdict == {criterion: True, issues: []}
    request = requests[0]
    assert json.loads(request["messages"][0]["content"])["reference_answer"] == "gold"
    schema = request["judge_schema"]
    validate({criterion: True, issues: []}, schema)
    validate({criterion: False, issues: ["An offending answer claim"]}, schema)
    for invalid in (
        {criterion: False, issues: []},
        {criterion: False, issues: [""]},
        {criterion: True, issues: ["An offending answer claim"]},
    ):
        with pytest.raises(ValidationError):
            validate(invalid, schema)
