#!/usr/bin/env python3
"""Publish validated artifacts, then atomically promote their digests in Hive."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from release import dump, git, update_hive


def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def main():
    root = Path.cwd()
    plan = json.loads((root / ".release/pending.json").read_text())
    sha = os.environ["RELEASE_SHA"]
    git("fetch", "origin", "main")
    if git("rev-parse", "origin/main") != sha:
        raise RuntimeError(
            "Main advanced; skip stale promotion and let its CI release accumulated changes"
        )
    results = [
        json.loads(p.read_text()) for p in (root / "release-results").glob("*.json")
    ]
    # Validate every planned digest and all target paths before publishing.
    update_hive(root / "hive", plan, results)
    cli_dir = root / "release-cli"
    if plan["cli"]:
        expected = {
            "kioku-linux-x64",
            "kioku-linux-arm64",
            "kioku-darwin-x64",
            "kioku-darwin-arm64",
            "kioku-windows-x64.exe",
        }
        if {p.name for p in cli_dir.iterdir()} != expected:
            raise RuntimeError("CLI artifacts missing or unexpected")
        for name in ("install.sh", "install.ps1"):
            shutil.copyfile(root / "scripts/release" / name, cli_dir / name)
        lines = [
            f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}"
            for p in sorted(cli_dir.iterdir())
        ]
        (cli_dir / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    dump(
        root / "release-manifest.json",
        {
            "commit": sha,
            "source": plan["source_sha"],
            "versions": plan["versions"],
            "images": results,
        },
    )
    tags = []
    for package, version in plan["versions"].items():
        tag = f"{package}-v{version}"
        tags.append(tag)
        existing = subprocess.run(
            ["gh", "release", "view", tag, "--json", "targetCommitish,isDraft"],
            check=False,
            capture_output=True,
            text=True,
        )
        if existing.returncode:
            run(
                "gh",
                "release",
                "create",
                tag,
                "--target",
                sha,
                "--draft",
                "--title",
                f"{package} {version}",
                "--notes",
                f"Source commit: {sha}\nAutomatically validated package release.",
            )
        else:
            data = json.loads(existing.stdout)
            if data["targetCommitish"] != sha:
                raise RuntimeError(f"Release {tag} points to another commit")
            if not data["isDraft"]:
                continue
        assets = [str(root / "release-manifest.json")]
        if package == "cli":
            assets += [str(p) for p in cli_dir.iterdir()]
        run("gh", "release", "upload", tag, *assets, "--clobber")
    # Push one normal Hive commit; on unrelated concurrent edits, retry from
    # fresh main and reapply only the exact image lines. Never force-push.
    hive = root / "hive"
    for attempt in range(3):
        if attempt:
            git("fetch", "origin", "main", cwd=hive)
            git("reset", "--hard", "origin/main", cwd=hive)
            update_hive(hive, plan, results)
        git("config", "user.name", "felipemeriga", cwd=hive)
        git("config", "user.email", "felipemeriga@users.noreply.github.com", cwd=hive)
        git("add", "kioku", cwd=hive)
        if not subprocess.run(
            ["git", "diff", "--cached", "--quiet"], cwd=hive, check=False
        ).returncode:
            break
        git("commit", "-m", f"chore(kioku): deploy release {sha[:12]}", cwd=hive)
        if (
            subprocess.run(
                ["git", "push", "origin", "HEAD:main"], cwd=hive, check=False
            ).returncode
            == 0
        ):
            break
    else:
        raise RuntimeError("Hive push failed; release drafts retained for retry")
    for tag in tags:
        run("gh", "release", "edit", tag, "--draft=false")
    ledger = f"release/deployed-{sha}"
    if not git("tag", "--list", ledger):
        git(
            "tag",
            "-a",
            ledger,
            sha,
            "-m",
            "All artifacts published and Hive promotion committed",
        )
    git("push", "origin", f"refs/tags/{ledger}")


if __name__ == "__main__":
    main()
