"""Guard contamination, private outputs and transport outcomes in live audits."""

import hashlib
import json
import stat
import subprocess

import pytest

from eval.memory_audit import live_replay

CEILING = "2026-11-27T04:53:34Z"


def sealed(tmp_path, cutoff=CEILING):
    path = tmp_path / "questions.json"
    path.write_text(
        json.dumps(
            {
                "queries": [
                    {
                        "case_id": "q",
                        "question": "A past decision?",
                        "filters": {"folder": "kioku", "as_of": cutoff},
                    }
                ]
            }
        )
    )
    return path, hashlib.sha256(path.read_bytes()).hexdigest(), tmp_path / "results.jsonl"


def no_requests(*args, **kwargs):
    raise AssertionError("No network call should be attempted")


def test_late_cutoff_cannot_index_or_retrieve_the_audits_own_answers(tmp_path, monkeypatch):
    source, digest, output = sealed(tmp_path, "2026-11-27T04:53:34.000001Z")
    monkeypatch.setattr(live_replay, "invoke", no_requests)
    with pytest.raises(ValueError, match="contamination cutoff"):
        live_replay.run(source, digest, output, 10, CEILING)
    assert not output.exists()


def test_modified_questions_abort_before_opening_output_or_calling_cli(tmp_path, monkeypatch):
    source, digest, output = sealed(tmp_path)
    source.write_text(source.read_text() + " ")
    monkeypatch.setattr(live_replay, "invoke", no_requests)
    with pytest.raises(ValueError, match="manifest changed"):
        live_replay.run(source, digest, output, 10, CEILING)
    assert not output.exists()


def test_real_source_outputs_are_private_and_completion_is_explicit(tmp_path, monkeypatch):
    source, digest, output = sealed(tmp_path)
    calls = []

    def invoke(args, timeout):
        calls.append(args)
        return {"status": "ok", "ms": 1, "result": {"status": "ok", "matches": []}}

    monkeypatch.setattr(live_replay, "invoke", invoke)
    live_replay.run(source, digest, output, 10, CEILING)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert [row["record_type"] for row in rows] == ["run", "trial", "completion"]
    assert rows[-1]["cases"] == 1
    assert calls == [
        [
            "history",
            "A past decision?",
            "--order",
            "relevance",
            "--limit",
            "10",
            "--folder",
            "kioku",
            "--as-of",
            CEILING,
        ]
    ]


def test_live_outputs_cannot_overwrite_an_earlier_observation(tmp_path, monkeypatch):
    source, digest, output = sealed(tmp_path)
    output.write_text("earlier run")
    monkeypatch.setattr(live_replay, "invoke", no_requests)
    with pytest.raises(FileExistsError):
        live_replay.run(source, digest, output, 10, CEILING)
    assert output.read_text() == "earlier run"


def test_zero_process_exit_does_not_turn_a_tool_error_into_success(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='{"status":"error","code":"evidence_query_timeout"}',
            stderr="",
        ),
    )
    result = live_replay.invoke(["history", "question"], 10)
    assert result["status"] == "cli_error"
    assert result["error_code"] == "evidence_query_timeout"
