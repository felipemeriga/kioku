"""Long-session bookkeeping only; never represented as real E2E evidence."""

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def probe():
    path = Path(__file__).parents[2] / "scripts" / "tsukai_http_acceptance.py"
    spec = importlib.util.spec_from_file_location("acceptance_http", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def no_creation():
    raise AssertionError("Reused conversations must not create another conversation")


def test_reuse_preserves_identity_first_code_and_policy_scope(probe):
    state = {"conversations": {"key": {"id": "existing", "nonce": "first", "filename": "guide"}}}
    fixture, created = probe.prepare_seed(state, "key", no_creation, "different", True, "second")
    assert not created
    assert fixture == {
        "id": "existing",
        "first_nonce": "first",
        "nonce": "second",
        "filename": "guide",
        "initial_seed": False,
    }
    fixture, created = probe.prepare_seed(state, "key", no_creation, reuse=True, nonce="third")
    assert not created and fixture["id"] == "existing"
    assert fixture["first_nonce"] == "first" and fixture["nonce"] == "third"


def test_default_fresh_behavior_still_creates_each_seed(probe):
    calls = []

    def create():
        calls.append(len(calls) + 1)
        return str(calls[-1])

    state = {"conversations": {}}
    first, first_created = probe.prepare_seed(state, "key", create, nonce="one")
    second, second_created = probe.prepare_seed(state, "key", create, nonce="two")
    assert first_created and second_created and calls == [1, 2]
    assert first["id"] != second["id"]
    assert first["first_nonce"] == first["nonce"] == "one"
    assert second["first_nonce"] == second["nonce"] == "two"
    assert probe.message_content(second, True, False, "Question") == (
        "Remember this acceptance code: two. Include it in your answer. Question"
    )


def test_pending_retry_never_changes_current_code_or_request(probe):
    state = {
        "pending": {"turn_id": "stable"},
        "conversations": {
            "key": {
                "id": "existing",
                "nonce": "current",
                "first_nonce": "first",
                "initial_seed": False,
            }
        },
    }
    before = probe.message_content(state["conversations"]["key"], True, True, "Question")
    fixture, created = probe.prepare_seed(
        state, "key", no_creation, reuse=True, nonce="must-not-apply"
    )
    assert not created and fixture["nonce"] == "current"
    assert probe.message_content(fixture, True, True, "Question") == before


def test_long_recall_prompt_injects_neither_expected_code(probe):
    fixture = {"nonce": "current-secret-test-code", "first_nonce": "initial-secret-test-code"}
    prompt = probe.message_content(fixture, False, True, "Unused")
    assert "FIRST" in prompt and "CURRENT" in prompt
    assert fixture["nonce"] not in prompt and fixture["first_nonce"] not in prompt
    assert probe.required_codes(fixture, False, True) == {fixture["nonce"], fixture["first_nonce"]}
    assert probe.required_codes(fixture, True, True) == {fixture["nonce"]}
    assert probe.required_codes(fixture, False, False) == {fixture["nonce"]}


def test_new_reused_conversation_starts_first_equal_current(probe):
    state = {"conversations": {}}
    fixture, created = probe.prepare_seed(state, "key", lambda: "new", reuse=True, nonce="initial")
    assert created and fixture["first_nonce"] == fixture["nonce"] == "initial"
    assert "FIRST and CURRENT" in probe.message_content(fixture, True, True, "Question")
    assert probe.required_codes(fixture, False, True) == {"initial"}
