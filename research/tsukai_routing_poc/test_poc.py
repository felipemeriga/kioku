import time
import unittest

import poc


class ScopeTests(unittest.TestCase):
    def setUp(self):
        poc.KEY = b"fixture-test-only-not-a-secret"

    def test_signed_scope_rejects_owner_tampering(self):
        grant = poc.capability("mihari")
        self.assertTrue(poc.valid(grant, "mihari"))
        grant["user"] = "other-owner"
        self.assertFalse(poc.valid(grant, "mihari"))

    def test_signed_scope_rejects_wrong_caller(self):
        self.assertFalse(poc.valid(poc.capability("mcp"), "mihari"))

    def test_expired_grant_fails_closed(self):
        grant = poc.capability("backend")
        grant["expires"] = int(time.time()) - 1
        self.assertFalse(poc.valid(grant, "backend"))


if __name__ == "__main__":
    unittest.main()
