"""Pure operation schemas and evidence checks: no provider or database calls."""

from copy import deepcopy

import pytest

from services.maintenance.operations import OPERATIONS, SHAPES, build_request, validate_result


def snapshot(operation, current=None):
    return {
        "operation": operation,
        "input": {
            "selected": ["overview"],
            "files": [{"path": "main.py", "content": "pass"}],
            "new_entries": [],
        },
        "current": current,
        "expected_sections": {},
    }


@pytest.mark.parametrize("operation", OPERATIONS)
def test_every_operation_has_pure_strict_schema(operation):
    request = build_request(snapshot(operation))
    assert request["schema"]["additionalProperties"] is False
    assert set(request["schema"]["required"]) == set(request["schema"]["properties"])
    assert "untrusted DATA" in request["system"]
    assert request["prompt"] == build_request(snapshot(operation))["prompt"]


@pytest.mark.parametrize("operation", OPERATIONS)
def test_needs_input_never_becomes_publishable(operation):
    with pytest.raises(ValueError, match="nonpublishable"):
        validate_result(
            snapshot(operation),
            {
                "schema_version": 1,
                "outcome": "needs_input",
                "data": None,
                "missing_inputs": [{"field": "source", "reason": "missing"}],
            },
        )


@pytest.mark.parametrize("operation", OPERATIONS)
def test_extra_fields_are_rejected(operation):
    value = deepcopy(SHAPES.get(operation, {"overview": SHAPES["overview"]}))
    value["injected"] = "fact"
    with pytest.raises(ValueError, match="shape"):
        validate_result(snapshot(operation), value)


def test_learning_requires_exact_quote_and_sha_in_cited_source():
    snap = snapshot("learnings", [])
    snap["input"]["new_entries"] = [
        {"id": "e1", "text": "Confirmed database section writes serialize on the folder row."}
    ]
    update = {
        "topic_key": "section-lock",
        "statement": "Section writes serialize on the folder row.",
        "source_ids": ["e1"],
        "evidence_quote": "section writes serialize on the folder row",
        "git_sha": None,
        "retire": False,
    }
    assert validate_result(snap, {"updates": [update]})["updates"] == [update]
    for mutation in (
        {"source_ids": ["foreign"]},
        {"evidence_quote": "invented statement"},
        {"git_sha": "a" * 40},
        {"retire": True},
    ):
        with pytest.raises(ValueError):
            validate_result(snap, {"updates": [{**update, **mutation}]})


def test_reground_can_shorten_legacy_detail_but_cannot_invent_component_paths():
    snap = snapshot("reground", {"architecture": {"summary": "Detailed" * 100}})
    snap["input"]["selected"] = ["architecture"]
    output = {"architecture": {"summary": "API", "components": [], "data_flow": "Calls handler"}}
    assert validate_result(snap, output) == output
    snap["current"] = {}
    output["architecture"]["components"] = [
        {"name": "API", "role": "Calls", "path": "imaginary.py"}
    ]
    with pytest.raises(ValueError, match="source path"):
        validate_result(snap, output)


def test_review_plan_excludes_user_owned_sections():
    snap = snapshot("review_plan")
    snap["expected_sections"] = {"overview": {"provenance": "user_ui"}}
    assert validate_result(snap, {"selected": ["overview", "deployment"]}) == {
        "selected": ["activity", "deployment"]
    }


def test_native_outcome_schema_accepts_missing_input_without_publishing():
    from jsonschema import Draft202012Validator

    from services.maintenance.operations import completion_schema

    schema = completion_schema(build_request(snapshot("activity"))["schema"])
    needs_input = {
        "schema_version": 1,
        "outcome": "needs_input",
        "data": None,
        "missing_inputs": [{"field": "commits", "reason": "No evidence"}],
        "failure": None,
        "warnings": [],
    }
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(needs_input)
    with pytest.raises(ValueError, match="nonpublishable"):
        validate_result(snapshot("activity"), needs_input)


def test_review_plan_excludes_documentation_even_when_a_guide_exists():
    snap = snapshot("review_plan")
    snap["documentation_revision"] = None
    assert validate_result(snap, {"selected": ["documentation", "how_it_runs"]}) == {
        "selected": ["activity", "how_it_runs"]
    }
    snap["documentation_revision"] = "existing-document-id"
    assert validate_result(snap, {"selected": ["documentation"]}) == {"selected": ["activity"]}


def test_learning_generation_schema_enforces_quote_bounds_and_source_ids():
    from jsonschema import ValidationError, validate

    snap = snapshot("learnings", [])
    snap["input"]["new_entries"] = [{"id": "source-1", "text": "Verified evidence from source."}]
    schema = build_request(snap)["schema"]
    update = {
        "topic_key": "verified-fact",
        "statement": "A verified durable fact.",
        "source_ids": ["source-1"],
        "evidence_quote": "Verified evidence from source.",
        "git_sha": None,
        "retire": False,
    }
    validate({"updates": [update]}, schema)
    for mutation in ({"evidence_quote": "x" * 251}, {"source_ids": ["invented"]}):
        with pytest.raises(ValidationError):
            validate({"updates": [{**update, **mutation}]}, schema)


@pytest.mark.parametrize("operation", ["documentation"])
def test_large_existing_guides_get_a_bounded_preservation_budget(operation):
    small = snapshot(operation, {"content": "Small guide"})
    large = snapshot(operation, {"content": "Verified existing detail. " * 1000})
    assert build_request(small)["max_tokens"] == 4000
    assert 4000 < build_request(large)["max_tokens"] <= 12000
    large["current"]["content"] *= 10
    assert build_request(large)["max_tokens"] == 12000


def architecture_snapshot(path):
    snap = snapshot("reground", {})
    snap["input"].update(
        selected=["architecture"],
        files=[{"path": "backend/main.py", "content": "pass"}],
        structure="backend/mcp_server.py\nbackend/Dockerfile.mcp\nbackend/routes\n",
    )
    output = {
        "architecture": {
            "summary": "API and MCP entry points.",
            "data_flow": "Requests reach the API.",
            "components": [{"name": "MCP", "role": "Repository tools", "path": path}],
        }
    }
    return snap, output


@pytest.mark.parametrize(
    "path",
    [
        "backend/mcp_server.py, backend/Dockerfile.mcp",
        "./backend/main.py, backend/routes/",
        "backend/",
        "backend/routes/",
    ],
)
def test_architecture_accepts_every_proven_legacy_group_member_and_normalized_directory(path):
    snap, output = architecture_snapshot(path)
    assert validate_result(snap, output) == output


@pytest.mark.parametrize(
    "path,unsupported",
    [
        ("backend/mcp_server.py, invented.py", "invented.py"),
        ("backend/mai", "backend/mai"),
        ("backend/routes/invented.py", "backend/routes/invented.py"),
        ("backend/main.py,", "''"),
        ("backend/main.py, ../secret.py", "../secret.py"),
    ],
)
def test_architecture_rejects_one_invented_member_prefix_or_unproven_child(path, unsupported):
    snap, output = architecture_snapshot(path)
    with pytest.raises(ValueError, match="unsupported source path") as error:
        validate_result(snap, output)
    assert unsupported in str(error.value)


def test_architecture_generation_schema_chooses_one_exact_evidenced_path():
    from jsonschema import ValidationError, validate

    snap, output = architecture_snapshot("backend/mcp_server.py")
    schema = build_request(snap)["schema"]
    validate(output, schema)
    output["architecture"]["components"][0]["path"] = (
        "backend/mcp_server.py, backend/Dockerfile.mcp"
    )
    with pytest.raises(ValidationError):
        validate(output, schema)
    output["architecture"]["components"][0]["path"] = "backend/routes/invented.py"
    with pytest.raises(ValidationError):
        validate(output, schema)


def test_learning_quotes_are_schema_constrained_to_exact_cited_source_excerpts():
    from jsonschema import ValidationError, validate

    snap = snapshot("learnings", [])
    text = "Confirmed `folder_id` isolation.\n" + "Long evidence " * 30
    snap["input"]["new_entries"] = [{"id": "entry-1", "text": text}]
    request = build_request(snap)
    quotes = request["schema"]["properties"]["updates"]["items"]["properties"]["evidence_quote"][
        "enum"
    ]
    assert quotes and all(q in text and 12 <= len(q) <= 250 for q in quotes)
    assert "Confirmed `folder_id` isolation." in quotes
    update = {
        "topic_key": "folder-isolation",
        "statement": "Folder identifiers provide isolation.",
        "source_ids": ["entry-1"],
        "evidence_quote": quotes[0],
        "git_sha": None,
        "retire": False,
    }
    validate({"updates": [update]}, request["schema"])
    validate_result(snap, {"updates": [update]})
    with pytest.raises(ValidationError):
        validate(
            {"updates": [{**update, "evidence_quote": "Paraphrased folder isolation."}]},
            request["schema"],
        )
    assert "Evidence choices:" in request["prompt"]


def test_learning_without_quotable_evidence_can_only_return_zero_updates():
    from jsonschema import ValidationError, validate

    snap = snapshot("learnings", [])
    snap["input"]["new_entries"] = [{"id": "tiny", "text": "Short"}]
    schema = build_request(snap)["schema"]
    validate({"updates": []}, schema)
    with pytest.raises(ValidationError):
        validate({"updates": [SHAPES["learnings"]["updates"][0]]}, schema)


@pytest.mark.parametrize("same_statement", [True, False])
def test_learning_duplicate_topics_are_rejected_before_publication(same_statement):
    snap = snapshot("learnings", [])
    snap["input"]["new_entries"] = [
        {"id": "e1", "text": "Confirmed folder writes serialize on the folder row."}
    ]
    update = {
        "topic_key": "folder-lock",
        "statement": "Folder writes serialize on the folder row.",
        "source_ids": ["e1"],
        "evidence_quote": "folder writes serialize on the folder row",
        "git_sha": None,
        "retire": False,
    }
    second = {
        **update,
        "statement": update["statement"]
        if same_statement
        else "Folder updates are serialized through the same lock.",
    }
    with pytest.raises(ValueError, match="duplicate learning topic"):
        validate_result(snap, {"updates": [update, second]})
    assert (
        len(
            validate_result(snap, {"updates": [update, {**second, "topic_key": "another-lock"}]})[
                "updates"
            ]
        )
        == 2
    )


def test_learning_commit_schema_requires_verbatim_full_source_hash():
    from jsonschema import ValidationError, validate

    snap = snapshot("learnings", [])
    full_sha = "a" * 40
    main_only = "b" * 40
    snap["input"].update(
        new_entries=[
            {
                "id": "e1",
                "text": f"Verified commit {full_sha}; abbreviated bbbbbbbb; checksum {'c' * 64}.",
            }
        ],
        main_commits=[main_only],
    )
    request = build_request(snap)
    field = request["schema"]["properties"]["updates"]["items"]["properties"]["git_sha"]
    assert field["enum"] == [None, full_sha]
    validate(None, field)
    validate(full_sha, field)
    with pytest.raises(ValidationError):
        validate(main_only, field)
    snap["input"]["new_entries"] = [
        {"id": "e1", "text": "Verified abbreviated commit bbbbbbbb only."}
    ]
    field = build_request(snap)["schema"]["properties"]["updates"]["items"]["properties"]["git_sha"]
    assert field["enum"] == [None]
    validate(None, field)
    assert "never expand" in request["prompt"]


def test_reground_budget_stays_concise_with_legacy_essays():
    assert (
        build_request(snapshot("reground", {"content": "Legacy essay. " * 10000}))["max_tokens"]
        == 4000
    )
