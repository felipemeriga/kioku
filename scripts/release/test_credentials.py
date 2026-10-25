import subprocess
import unittest
from unittest.mock import Mock, patch

from probe_credentials import probe_hive, require_hive_read


class CredentialTests(unittest.TestCase):
    def test_metadata_access_does_not_establish_contents_access(self):
        with patch(
            "probe_credentials.probe_hive",
            return_value={
                "metadata_status": 200,
                "contents_status": 403,
                "isolated_git_read": False,
            },
        ):
            with self.assertRaisesRegex(RuntimeError, "Contents"):
                require_hive_read("fixture-token")

    def test_contents_denial_never_attempts_write_and_token_never_in_argv(self):
        request = Mock(side_effect=[(200, {}), (403, None)])
        with (
            patch("probe_credentials.github_request", request),
            patch(
                "probe_credentials.subprocess.run",
                return_value=subprocess.CompletedProcess([], 128),
            ) as run,
        ):
            result = probe_hive("fixture-token", write=True)
        self.assertFalse(result["isolated_git_read"])
        self.assertEqual(request.call_count, 2)
        self.assertNotIn("fixture-token", str(run.call_args.args))

    def test_write_probe_creates_and_deletes_only_a_unique_nonmain_ref(self):
        request = Mock(
            side_effect=[
                (200, {}),
                (200, {}),
                (200, {"object": {"sha": "a" * 40}}),
                (201, {}),
                (204, None),
            ]
        )
        with (
            patch.dict("os.environ", {"GITHUB_RUN_ID": "12345"}),
            patch("probe_credentials.github_request", request),
            patch(
                "probe_credentials.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0),
            ),
        ):
            result = probe_hive("fixture-token", write=True)
        self.assertEqual(result["create_probe_ref_status"], 201)
        self.assertEqual(result["delete_probe_ref_status"], 204)
        create = request.call_args_list[3]
        self.assertEqual(
            create.args[3]["ref"], "refs/heads/kioku-cd-permission-probe-12345"
        )
        self.assertEqual(request.call_args_list[4].args[2], "DELETE")
