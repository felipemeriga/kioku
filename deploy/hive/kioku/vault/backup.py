#!/usr/bin/env python3
"""Encrypted database backup. Recipient key and encryption-root escrow are separate."""

import argparse
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--recipient", required=True, help="age public recipient, never a private key"
    )
    parser.add_argument("--directory", required=True, type=Path)
    args = parser.parse_args()
    args.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = args.directory / (
        "kioku-vault-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + ".dump.age"
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    dump = None
    failed = False
    try:
        with os.fdopen(fd, "wb") as output:
            dump = subprocess.Popen(
                [
                    "docker",
                    "exec",
                    "kioku-vault-db",
                    "pg_dump",
                    "-U",
                    "infisical",
                    "-d",
                    "infisical",
                    "-Fc",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            encrypted = subprocess.run(
                ["age", "-r", args.recipient],
                stdin=dump.stdout,
                stdout=output,
                stderr=subprocess.DEVNULL,
                timeout=180,
            )
            dump.stdout.close()
            dump.wait(timeout=30)
            if dump.returncode or encrypted.returncode:
                failed = True
    except Exception:
        failed = True
    finally:
        if dump is not None:
            if dump.stdout is not None and not dump.stdout.closed:
                dump.stdout.close()
            if dump.poll() is None:
                dump.kill()
                try:
                    dump.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    failed = True
        if failed:
            path.unlink(missing_ok=True)
    if failed:
        raise SystemExit(
            "Backup failed. No plaintext or partial encrypted backup was retained."
        )
    backups = sorted(
        args.directory.glob("kioku-vault-????????T??????Z.dump.age"), reverse=True
    )
    keep = set()
    days = set()
    weeks = set()
    for backup in backups:
        stamp = backup.name.removeprefix("kioku-vault-").removesuffix(".dump.age")
        try:
            recorded = datetime.strptime(stamp, "%Y%m%dT%H%M%SZ")
            week = recorded.isocalendar()[:2]
            day = recorded.date()
        except ValueError:
            continue
        if day not in days and len(days) < 7:
            days.add(day)
            keep.add(backup)
        if week not in weeks and len(weeks) < 4:
            weeks.add(week)
            keep.add(backup)
    for backup in backups:
        if backup not in keep:
            backup.unlink()
    print(
        "Encrypted vault backup created. Encryption-root material must be escrowed separately."
    )


if __name__ == "__main__":
    main()
