import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from native import NativeRunner


class NativeProcessTests(unittest.TestCase):
    def fake_cli(self, directory, body):
        executable = directory / "claude"
        executable.write_text(f"#!{sys.executable}\n" + body)
        executable.chmod(0o700)

    def test_native_auth_environment_has_no_api_fallback(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fake_cli(
                root,
                "import json,os,sys\nsys.stdin.read()\n"
                "assert 'ANTHROPIC_API_KEY' not in os.environ\n"
                "print(json.dumps({'type':'result','result':'OK','session_id':'fixture',"
                "'is_error':False,'subtype':'success','total_cost_usd':0.01}))\n",
            )
            with patch.dict(
                os.environ, {"PATH": str(root), "ANTHROPIC_API_KEY": "synthetic"}
            ):
                result = NativeRunner(root / "runtime").call(
                    "fixture", "question", persist=False
                )
            self.assertEqual(result["returncode"], 0)
            self.assertEqual(result["result"], "OK")
            rows = (root / "runtime/calls.jsonl").read_text().splitlines()
            self.assertEqual(len(rows), 1)
            self.assertEqual(json.loads(rows[0])["list_cost_usd"], 0.01)

    def test_timeout_terminates_process_then_next_call_can_run(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fake_cli(root, "import time\ntime.sleep(30)\n")
            with patch.dict(os.environ, {"PATH": str(root)}):
                runner = NativeRunner(root / "runtime")
                result = runner.call("timeout", "question", timeout=0.2)
                self.assertNotEqual(result["returncode"], 0)
                self.assertLess(result["elapsed_s"], 5)
                self.fake_cli(
                    root,
                    "import json\nprint(json.dumps({'type':'result','result':'RECOVERED'}))\n",
                )
                recovery = runner.call("recovery", "question")
                self.assertEqual(recovery["result"], "RECOVERED")

    def test_zero_exit_without_terminal_result_is_not_success(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            self.fake_cli(root, "print('non-json diagnostic')\n")
            with patch.dict(os.environ, {"PATH": str(root)}):
                result = NativeRunner(root / "runtime").call(
                    "missing-result", "question"
                )
            self.assertEqual(result["returncode"], 0)
            self.assertTrue(result["is_error"])
            self.assertFalse(result["terminal_result_seen"])


if __name__ == "__main__":
    unittest.main()
