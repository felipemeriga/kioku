import os
import unittest
from unittest.mock import patch


class TestCrypto(unittest.TestCase):
    def setUp(self):
        # Fernet key is 32 url-safe base64 bytes. Use a deterministic test key.
        self.test_key = "kX3Q1Y6uJcC5V0X6UeMHnf4Y4v1eYlDqfM3sFq5aBcE="

    def test_encrypt_decrypt_roundtrip(self):
        with patch.dict(os.environ, {"NOTION_TOKEN_ENCRYPTION_KEY": self.test_key}):
            from services.crypto import decrypt_secret, encrypt_secret

            token = "secret_ABCDEF123456"
            ciphertext = encrypt_secret(token)
            self.assertNotEqual(ciphertext, token)
            self.assertEqual(decrypt_secret(ciphertext), token)

    def test_encrypt_is_non_deterministic(self):
        with patch.dict(os.environ, {"NOTION_TOKEN_ENCRYPTION_KEY": self.test_key}):
            from services.crypto import encrypt_secret

            a = encrypt_secret("same-input")
            b = encrypt_secret("same-input")
            self.assertNotEqual(a, b, "Fernet uses a per-encryption IV")

    def test_missing_key_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            import importlib

            import services.crypto as crypto_mod

            importlib.reload(crypto_mod)
            with self.assertRaises(RuntimeError):
                crypto_mod.encrypt_secret("x")
