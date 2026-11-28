"""Durability coordinator must reject failed or incomplete study receipts."""

import json
import tempfile
import unittest
from pathlib import Path

from finish_run import terminal_receipt, verify_runtime


class CompletionGuards(unittest.TestCase):
    def test_only_complete_successful_duration_and_matching_samples_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "study.jsonl"
            samples = [{"type": "start"}, {"iteration": 0, "status": "ok"}]
            terminal = {
                "type": "complete",
                "iterations": 1,
                "failures": 0,
                "tested_seconds": 1.0,
            }

            def write(rows):
                path.write_text("".join(json.dumps(r) + "\n" for r in rows))

            write(samples)
            with self.assertRaisesRegex(ValueError, "terminal"):
                terminal_receipt(path, "tested_seconds", 1)
            write(samples + [terminal | {"failures": 1}])
            with self.assertRaisesRegex(ValueError, "failed"):
                terminal_receipt(path, "tested_seconds", 1)
            write(samples + [terminal | {"tested_seconds": 0.5}])
            with self.assertRaisesRegex(ValueError, "duration"):
                terminal_receipt(path, "tested_seconds", 1)
            write(samples + [terminal | {"iterations": 2}])
            with self.assertRaisesRegex(ValueError, "sample"):
                terminal_receipt(path, "tested_seconds", 1)
            write(samples + [terminal])
            self.assertEqual(terminal_receipt(path, "tested_seconds", 1), terminal)

    def test_runtime_must_be_the_same_healthy_loopback_only_experiment(self):
        expected = {"id": "experiment-id", "image": "pinned-image"}
        actual = expected | {
            "project": "kioku-c360-temporal-poc",
            "running": "true",
            "oom": "false",
            "ports": json.dumps(
                {"7687/tcp": [{"HostIp": "127.0.0.1", "HostPort": "17687"}]}
            ),
        }
        verify_runtime(actual, expected)
        with self.assertRaisesRegex(ValueError, "isolated"):
            verify_runtime(actual | {"project": "other-project"}, expected)
        with self.assertRaisesRegex(ValueError, "isolated"):
            verify_runtime(actual | {"id": "different-container"}, expected)
        with self.assertRaisesRegex(ValueError, "loopback"):
            verify_runtime(
                actual | {"ports": json.dumps({"7687/tcp": [{"HostIp": "0.0.0.0"}]})},
                expected,
            )


if __name__ == "__main__":
    unittest.main()
