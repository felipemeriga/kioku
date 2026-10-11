"""At-rest secret encryption.

New writes use **AWS KMS** directly (all our secrets — SSH private keys, Notion
tokens, API keys — are well under KMS's 4 KB plaintext limit, so no envelope/DEK
machinery is needed). Reads transparently handle BOTH the new KMS ciphertext and
legacy Fernet ciphertext during the migration, so nothing breaks mid-rollout.

Env:
  KIOKU_KMS_KEY_ID             KMS key id / ARN / alias (required to encrypt)
  AWS_REGION | AWS_DEFAULT_REGION, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
  NOTION_TOKEN_ENCRYPTION_KEY  legacy Fernet key — read-only fallback; keep set
                               until all rows are re-sealed, then it can be removed.

Rotation of the KMS key is automatic (AWS, transparent — the ARN is stable and
old ciphertext keeps decrypting). See docs for IAM-credential rotation.
"""

import base64
import os
from functools import lru_cache

# Distinguishes new KMS ciphertext from legacy Fernet tokens (which are urlsafe
# base64 and never contain ':').
_KMS_PREFIX = "kms:v1:"
# KMS AAD — bound on encrypt, required (and verified) on decrypt.
_ENC_CONTEXT = {"app": "kioku"}


@lru_cache(maxsize=1)
def _kms():
    import boto3

    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    return boto3.client("kms", region_name=region)


def _kms_key_id() -> str:
    kid = os.environ.get("KIOKU_KMS_KEY_ID")
    if not kid:
        raise RuntimeError("KIOKU_KMS_KEY_ID is not set — cannot encrypt secrets.")
    return kid


@lru_cache(maxsize=1)
def _fernet():
    from cryptography.fernet import Fernet

    key = os.environ.get("NOTION_TOKEN_ENCRYPTION_KEY")
    return Fernet(key.encode()) if key else None


def encrypt_secret(plaintext: str) -> str:
    resp = _kms().encrypt(
        KeyId=_kms_key_id(),
        Plaintext=plaintext.encode(),
        EncryptionContext=_ENC_CONTEXT,
    )
    return _KMS_PREFIX + base64.b64encode(resp["CiphertextBlob"]).decode()


def decrypt_secret(ciphertext: str) -> str:
    if ciphertext.startswith(_KMS_PREFIX):
        blob = base64.b64decode(ciphertext[len(_KMS_PREFIX) :])
        resp = _kms().decrypt(CiphertextBlob=blob, EncryptionContext=_ENC_CONTEXT)
        return resp["Plaintext"].decode()
    # Legacy Fernet (rows written before the KMS migration).
    fernet = _fernet()
    if fernet is None:
        raise RuntimeError(
            "Got legacy Fernet ciphertext but NOTION_TOKEN_ENCRYPTION_KEY is not set."
        )
    return fernet.decrypt(ciphertext.encode()).decode()
