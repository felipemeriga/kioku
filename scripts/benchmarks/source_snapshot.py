"""Freeze a complete production git archive and its Python source lock."""

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

from benchmark_guard import REQUIRED_SOURCES, prompt_hash


def create_snapshot(repo, revision, output):
    repo, output = Path(repo), Path(output)
    commit = subprocess.check_output(
        ["git", "rev-parse", "--verify", revision + "^{commit}"], cwd=repo, text=True
    ).strip()
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    archive = output / "production.tar"
    with archive.open("xb") as stream:
        subprocess.run(
            ["git", "archive", "--format=tar", commit],
            cwd=repo,
            stdout=stream,
            check=True,
        )
    archive.chmod(0o600)
    files = {}
    with tarfile.open(archive) as contents, tempfile.TemporaryDirectory() as scratch:
        for member in contents.getmembers():
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Unsafe production archive path")
            if not member.isfile() or path.suffix != ".py":
                continue
            if not (
                member.name.startswith("backend/")
                or member.name.startswith("tsukai/src/")
            ):
                continue
            value = contents.extractfile(member).read()
            files[member.name] = hashlib.sha256(value).hexdigest()
            if member.name in {
                "backend/services/rag.py",
                "backend/services/ai/chat.py",
            }:
                target = Path(scratch) / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(value)
        if not REQUIRED_SOURCES <= set(files):
            raise ValueError("Production archive is missing required sources")
        lock = {
            "production_commit": commit,
            "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
            "system_prompt_sha256": prompt_hash(scratch),
            "files": files,
        }
    path = output / "source-lock.json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(lock, stream, indent=2, sort_keys=True)
    return lock


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    lock = create_snapshot(args.repo, args.revision, args.output)
    print(
        json.dumps(
            {
                "production_commit": lock["production_commit"],
                "source_files": len(lock["files"]),
            }
        )
    )
