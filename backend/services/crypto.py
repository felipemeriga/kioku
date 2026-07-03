"""Fernet-based encryption for at-rest secrets (e.g. Notion integration tokens).

Reads the symmetric key from env var NOTION_TOKEN_ENCRYPTION_KEY. Generate a key
with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Rotation: if the key must change, re-encrypt all rows in a migration.
"""

import os
from functools import lru_cache

from cryptography.fernet import Fernet


@lru_cache(maxsize=1)
def _get_fernet() -> Fernet:
    key = os.environ.get("NOTION_TOKEN_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "NOTION_TOKEN_ENCRYPTION_KEY is not set. Generate one with "
            "python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'."
        )
    return Fernet(key.encode())


def encrypt_secret(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()
