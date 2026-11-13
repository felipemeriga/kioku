import base64
import pathlib
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch

from apple_signing import cleanup, prepare, validate_credentials, validate_signature


class AppleSigningTests(unittest.TestCase):
    def credentials(self):
        return {
            "APPLE_CERTIFICATE": base64.b64encode(b"fixture").decode(),
            "APPLE_CERTIFICATE_PASSWORD": "fixture password",
            "APPLE_SIGNING_IDENTITY": "Developer ID Application: Example (KFCS65DU8T)",
            "APPLE_API_KEY": "ABCDEFGHIJ",
            "APPLE_API_ISSUER": "11111111-2222-4333-8444-555555555555",
            "APPLE_API_KEY_P8": "-----BEGIN PRIVATE KEY-----\nfixture\n-----END PRIVATE KEY-----",
        }

    def test_production_rejects_missing_credentials_and_wrong_signing_team(self):
        validate_credentials(self.credentials())
        with self.assertRaisesRegex(ValueError, "Missing production Apple credentials"):
            validate_credentials({})
        for identity in [
            "-",
            "Apple Development: Example (KFCS65DU8T)",
            "Developer ID Application: Example (WRONGTEAM1)",
        ]:
            values = self.credentials()
            values["APPLE_SIGNING_IDENTITY"] = identity
            with self.assertRaisesRegex(ValueError, "Developer ID Application"):
                validate_credentials(values)

    def test_rejects_malformed_notary_inputs_without_exposing_values(self):
        for name in [
            "APPLE_CERTIFICATE",
            "APPLE_API_KEY",
            "APPLE_API_ISSUER",
            "APPLE_API_KEY_P8",
        ]:
            values = self.credentials()
            values[name] = "sensitive-invalid-value"
            with self.assertRaises(ValueError) as caught:
                validate_credentials(values)
            self.assertNotIn("sensitive-invalid-value", str(caught.exception))

    def test_release_requires_developer_id_team_and_hardened_runtime(self):
        details = "CodeDirectory flags=0x10000(runtime)\nAuthority=Developer ID Application: Example (KFCS65DU8T)\nTeamIdentifier=KFCS65DU8T\n"
        validate_signature(details)
        for invalid in [
            details.replace("KFCS65DU8T", "WRONGTEAM1"),
            details.replace("Developer ID Application", "Apple Development"),
            details.replace("0x10000", "0x0"),
        ]:
            with self.assertRaises(ValueError):
                validate_signature(invalid)

    def test_key_is_private_outside_checkout_and_removed_after_build(self):
        with tempfile.TemporaryDirectory() as temp:
            env = self.credentials() | {
                "RUNNER_TEMP": temp,
                "GITHUB_ENV": str(pathlib.Path(temp) / "env"),
            }
            with patch("apple_signing.subprocess.run", return_value=Mock(returncode=0)):
                key = prepare(env)
            self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
            self.assertFalse(key.is_relative_to(pathlib.Path.cwd()))
            self.assertEqual(key.read_text().strip(), env["APPLE_API_KEY_P8"])
            cleanup(env | {"APPLE_API_KEY_PATH": str(key)})
            self.assertFalse(key.parent.exists())
