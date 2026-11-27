"""Reject stale corpus reuse and byte/character locator confusion."""

from unittest.mock import Mock

import pytest

from eval.memory_audit.replay import SourceRecord, verify_reused_source


@pytest.mark.parametrize(
    "stored",
    [
        None,
        {"object_id": "other", "byte_length": 12, "sha256": "expected"},
        {"object_id": "segment-1", "byte_length": 13, "sha256": "expected"},
        {"object_id": "segment-1", "byte_length": 12, "sha256": "stale"},
    ],
)
def test_matching_segment_counts_do_not_authorize_reusing_different_sources(stored):
    store = Mock()
    with pytest.raises(ValueError, match="differs from the frozen source"):
        verify_reused_source(store, stored, 12, "expected")
    store.download.assert_not_called()


def test_a_matching_descriptor_still_requires_live_byte_verification():
    descriptor = {"object_id": "segment-1", "byte_length": 12, "sha256": "expected"}
    store = Mock()
    store.download.side_effect = RuntimeError("object_integrity_failure")
    with pytest.raises(RuntimeError, match="object_integrity_failure"):
        verify_reused_source(store, descriptor, 12, "expected")
    store.download.assert_called_once_with(descriptor)


def test_verified_source_can_be_reused_after_actual_download():
    descriptor = {"object_id": "segment-1", "byte_length": 12, "sha256": "expected"}
    store = Mock()
    verify_reused_source(store, descriptor, 12, "expected")
    store.download.assert_called_once_with(descriptor)


def test_non_ascii_continuation_distinguishes_utf8_bytes_and_character_offsets():
    text = "α🙂東京 tail"
    raw_record_size = len(text.encode()) + 80
    source = SourceRecord("segment-1", 137, raw_record_size, text)
    evidence = {
        "raw_record": {
            "object_id": "segment-1",
            "byte_offset": 137,
            "byte_length": raw_record_size,
        },
        "char_start": 2,
        "excerpt": "東京",
        "has_more": True,
    }
    assert source.validates(evidence)
    assert not source.validates({**evidence, "has_more": False})
    assert not source.validates({**evidence, "char_start": len("α🙂".encode())})
    assert not source.validates(
        {**evidence, "raw_record": {**evidence["raw_record"], "byte_offset": 138}}
    )
