import base64
import os
from unittest.mock import MagicMock, patch

import pytest


def test_encrypt_uses_kms_and_prefixes():
    import services.crypto as crypto

    fake = MagicMock()
    fake.encrypt.return_value = {"CiphertextBlob": b"RAWCIPHER"}
    with (
        patch.dict(os.environ, {"KIOKU_KMS_KEY_ID": "alias/test"}),
        patch("services.crypto._kms", return_value=fake),
    ):
        out = crypto.encrypt_secret("hunter2")

    assert out.startswith("kms:v1:")
    assert base64.b64decode(out[len("kms:v1:") :]) == b"RAWCIPHER"
    # AAD is bound on encrypt.
    assert fake.encrypt.call_args.kwargs["EncryptionContext"] == {"app": "kioku"}


def test_decrypt_kms_ciphertext():
    import services.crypto as crypto

    fake = MagicMock()
    fake.decrypt.return_value = {"Plaintext": b"hunter2"}
    token = "kms:v1:" + base64.b64encode(b"RAWCIPHER").decode()
    with patch("services.crypto._kms", return_value=fake):
        assert crypto.decrypt_secret(token) == "hunter2"
    assert fake.decrypt.call_args.kwargs["EncryptionContext"] == {"app": "kioku"}


def test_decrypt_falls_back_to_legacy_fernet():
    from cryptography.fernet import Fernet

    import services.crypto as crypto

    key = Fernet.generate_key().decode()
    token = Fernet(key.encode()).encrypt(b"legacy-secret").decode()
    # A legacy Fernet token must NOT trigger a KMS call.
    with (
        patch.dict(os.environ, {"NOTION_TOKEN_ENCRYPTION_KEY": key}),
        patch("services.crypto._kms", side_effect=AssertionError("KMS must not run")),
    ):
        crypto._fernet.cache_clear()
        assert crypto.decrypt_secret(token) == "legacy-secret"
    crypto._fernet.cache_clear()


def test_encrypt_requires_kms_key_id():
    import services.crypto as crypto

    with (
        patch("services.crypto._kms", return_value=MagicMock()),
        patch.dict(os.environ, {}, clear=True),
    ):
        with pytest.raises(RuntimeError):
            crypto.encrypt_secret("x")
