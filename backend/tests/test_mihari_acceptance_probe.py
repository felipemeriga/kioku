"""Acceptance evidence must accept truthful checkpoint retries without new AI."""

import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "tsukai_mihari_probe", Path(__file__).resolve().parents[2] / "scripts" / "tsukai_mihari_e2e.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def test_fresh_native_publication_proves_a_change():
    before, after = {"content": "old"}, {"content": "new"}
    evidence = probe.publication_change(before, after, {"snapshot": {"current": "old"}})
    assert evidence["before_digest"] != evidence["after_digest"]
    assert evidence["resumed_pass"] is False


def test_recovered_checkpoint_uses_original_snapshot_without_regeneration():
    before, after = {"content": "already published"}, {"content": "already published"}
    evidence = probe.publication_change(before, after, {"snapshot": {"current": "original facts"}})
    assert evidence["before_digest"] != evidence["after_digest"]
    assert evidence["observed_before_digest"] == evidence["after_digest"]
    assert evidence["resumed_pass"] is True


def test_unchanged_or_missing_original_evidence_cannot_claim_native_update():
    before = after = {"content": "same"}
    with pytest.raises(RuntimeError, match="did not change"):
        probe.publication_change(before, after, {"snapshot": {"current": "same"}})
    with pytest.raises(RuntimeError, match="missing"):
        probe.publication_change(before, after, {"publication": {"updated": True}})


def test_detailed_documentation_compares_full_original_revision_and_scoped_mcp_body():
    before = {"id": "old-doc", "content": "Poll every 5 seconds", "abstract": "Old abstract"}
    after = {"id": "new-doc", "content": "Poll every 10 seconds", "abstract": "New abstract"}
    evidence = probe.documentation_change(
        before, after, {"snapshot": {"current": before}}, before["content"], after["content"]
    )
    assert evidence["original_document_revision"] == "old-doc"
    assert evidence["document_revision"] == "new-doc"
    assert evidence["before_digest"] != evidence["after_digest"]
    assert evidence["scoped_mcp_full_body_verified"] is True
    assert evidence["resumed_pass"] is False
    recovered = probe.documentation_change(
        after, after, {"snapshot": {"current": before}}, after["content"], after["content"]
    )
    assert recovered["resumed_pass"] is True


def test_abstract_change_cannot_pretend_the_detailed_document_body_changed():
    before = {"id": "old-doc", "content": "same full body", "abstract": "old abstract"}
    after = {"id": "new-doc", "content": "same full body", "abstract": "new abstract"}
    with pytest.raises(RuntimeError, match="did not change"):
        probe.documentation_change(
            before, after, {"snapshot": {"current": before}}, before["content"], after["content"]
        )


@pytest.mark.parametrize("missing", ["revision", "snapshot", "mcp-body"])
def test_detailed_documentation_requires_full_revision_and_authoritative_scoped_tool(missing):
    before = {"id": "old-doc", "content": "old full body"}
    after = {"id": "new-doc", "content": "new full body"}
    prepared = {"snapshot": {"current": before}}
    if missing == "revision":
        after["id"] = "old-doc"
    if missing == "snapshot":
        prepared = {"snapshot": {"current": "briefing abstract"}}
    mcp_after = "different tool content" if missing == "mcp-body" else after["content"]
    with pytest.raises(RuntimeError):
        probe.documentation_change(before, after, prepared, before["content"], mcp_after)
