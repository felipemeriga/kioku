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
