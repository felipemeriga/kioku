#!/usr/bin/env python3
"""Create new protected vault keys without displaying them. Never overwrite keys."""

import argparse
import os
import secrets
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    args.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = args.directory / "vault.env"
    values = {
        "ENCRYPTION_KEY": secrets.token_hex(16),
        "AUTH_SECRET": secrets.token_urlsafe(40),
        "POSTGRES_PASSWORD": secrets.token_urlsafe(40),
        "KIOKU_VAULT_WRITE_HMAC_KEY": secrets.token_urlsafe(40),
        "POSTGRES_USER": "infisical",
        "POSTGRES_DB": "infisical",
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("".join(k + "=" + v + "\n" for k, v in values.items()))
    print(
        "Created protected vault.env. Back up encryption material separately before storing credentials."
    )


if __name__ == "__main__":
    main()
