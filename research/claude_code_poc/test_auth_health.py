import unittest

from auth_health import classify


class AuthHealthTest(unittest.TestCase):
    def test_actual_expired_error_requires_login(self):
        self.assertEqual(
            classify(
                {
                    "returncode": 1,
                    "result": "Failed to authenticate: OAuth session expired and could not be refreshed",
                }
            ),
            "reauth_required",
        )

    def test_refresh_contention_is_retryable(self):
        self.assertEqual(
            classify(
                {
                    "returncode": 1,
                    "result": "Could not refresh your login because another Claude Code process is refreshing it",
                }
            ),
            "refresh_in_progress",
        )

    def test_health_and_unknown(self):
        self.assertEqual(classify({"returncode": 0, "result": "HEALTH_OK"}), "healthy")
        self.assertEqual(
            classify({"returncode": 1, "result": "Connection refused"}),
            "degraded_unknown",
        )


if __name__ == "__main__":
    unittest.main()
