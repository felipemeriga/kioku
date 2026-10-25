import subprocess
import unittest
import urllib.error
from unittest.mock import MagicMock, Mock, patch

from credentials import require_hive_read


class CredentialTests(unittest.TestCase):
    def test_contents_denial_never_attempts_git(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError("url", 403, "denied", {}, None)
        with (
            patch("credentials.urllib.request.build_opener", return_value=opener),
            patch("credentials.subprocess.run") as run,
            self.assertRaisesRegex(RuntimeError, "Contents"),
        ):
            require_hive_read("fixture-token")
        run.assert_not_called()

    def test_git_read_uses_environment_not_argv(self):
        opener = Mock()
        response = MagicMock()
        response.__enter__.return_value.status = 200
        opener.open.return_value = response
        with (
            patch("credentials.urllib.request.build_opener", return_value=opener),
            patch(
                "credentials.subprocess.run",
                return_value=subprocess.CompletedProcess([], 0),
            ) as run,
        ):
            require_hive_read("fixture-token")
        self.assertNotIn("fixture-token", str(run.call_args.args))
