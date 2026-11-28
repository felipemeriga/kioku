import hashlib
import io
import json
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import live_replay


class ReplayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name)
        self.manifest = folder / "manifest.json"
        self.output = folder / "receipt.jsonl"
        example = {
            "case_id": "demo",
            "question": "--literal question",
            "filters": {"folder": "sample", "as_of": "2026-01-15T10:00:00Z"},
        }
        self.manifest.write_text(json.dumps({"queries": [example]}))
        self.digest = hashlib.sha256(self.manifest.read_bytes()).hexdigest()

    def replay(self, **options):
        with redirect_stdout(io.StringIO()):
            live_replay.run(
                self.manifest,
                self.digest,
                self.output,
                5,
                "2026-01-15T18:00:00Z",
                **options,
            )
        return [json.loads(line) for line in self.output.read_text().splitlines()]

    def test_hints_skip_evidence_and_preserve_literal_question(self):
        search = {
            "status": "ok",
            "ms": 1,
            "result": {
                "originals_searched": False,
                "journal_hints": [{"title": "Example report"}],
                "matches": [],
            },
        }
        with patch("live_replay.invoke", return_value=search) as invoke:
            rows = self.replay(
                strategy="journal-guided", evidence_mode="cached-preview"
            )
        invoke.assert_called_once()
        args = invoke.call_args.args[0]
        self.assertEqual(args[-2:], ["--", "--literal question"])
        self.assertIn("journal-guided", args)
        self.assertIn("cached-preview", args)
        self.assertEqual(rows[1]["metrics"]["journal_hints"], 1)
        self.assertEqual(rows[1]["metrics"]["signed_reads_attempted"], 0)
        self.assertEqual(rows[1]["metrics"]["original_excerpts"], 0)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o600)
        self.assertEqual(rows[-1], {"record_type": "completion", "cases": 1})

    def test_original_excerpt_locator_and_read_are_counted_separately(self):
        matches = [
            {"reference": "sample-first", "excerpt": "Sample excerpt"},
            {"reference": "sample-deferred", "requires_evidence_read": True},
        ]
        search = {"status": "ok", "ms": 1, "result": {"matches": matches}}
        opened = {
            "status": "ok",
            "result": {"evidence": [{"excerpt": "Sample original"}]},
        }
        empty = {"status": "ok", "result": {"evidence": []}}
        with patch("live_replay.invoke", side_effect=[search, opened, empty]):
            metrics = self.replay()[1]["metrics"]
        self.assertEqual(metrics["original_excerpts"], 1)
        self.assertEqual(metrics["deferred_locators"], 1)
        self.assertEqual(metrics["signed_reads_attempted"], 2)
        self.assertEqual(metrics["signed_reads_succeeded"], 1)

    def test_refuses_changed_manifest_future_cutoff_and_existing_output(self):
        with patch("live_replay.invoke") as invoke:
            with self.assertRaisesRegex(ValueError, "changed"):
                live_replay.run(
                    self.manifest, "0" * 64, self.output, 5, "2026-01-15T18:00:00Z"
                )
            with self.assertRaisesRegex(ValueError, "exceeds"):
                live_replay.run(
                    self.manifest, self.digest, self.output, 5, "2026-01-15T09:00:00Z"
                )
            self.assertFalse(self.output.exists())
            self.output.write_text("existing")
            with self.assertRaises(FileExistsError):
                self.replay()
            invoke.assert_not_called()
        self.assertEqual(self.output.read_text(), "existing")

    def test_structured_error_from_stderr_is_recorded_without_payload(self):
        failure = CompletedProcess(
            [], 1, stdout="", stderr="Kioku: evidence_query_timeout"
        )
        with patch("live_replay.subprocess.run", return_value=failure):
            outcome = live_replay.invoke(["history", "fixture"], 5)
        self.assertEqual(outcome["error_code"], "evidence_query_timeout")
        self.assertIsNone(outcome["result"])
