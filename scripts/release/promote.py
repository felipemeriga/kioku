#!/usr/bin/env python3
"""Publish validated artifacts, then atomically promote their digests in Hive."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from deployment import configuration, wait_for_deployments
from release import dump, git, update_hive


def run(*args, **kwargs):
    subprocess.run(args, check=True, **kwargs)


def assert_source_current(root, sha):
    git("fetch", "origin", "main", cwd=root)
    if git("rev-parse", "origin/main", cwd=root) != sha:
        raise RuntimeError(
            "Main advanced; skip stale promotion and release accumulated changes"
        )


def existing_hive_commit(hive, subject):
    candidates = git(
        "log", "HEAD", "--format=%H", "--fixed-strings", "--grep=" + subject, cwd=hive
    ).splitlines()
    for candidate in candidates:
        if git("log", "-1", "--format=%s", candidate, cwd=hive) == subject:
            return candidate
    raise RuntimeError(
        "No matching Hive promotion commit found; cannot verify an already-pinned release"
    )


def main():
    root = Path.cwd()
    plan = json.loads((root / ".release/pending.json").read_text())
    sha = os.environ["RELEASE_SHA"]
    if plan.get("release_branch", "main") != "main":
        raise ValueError("Release plan must target main")
    assert_source_current(root, sha)
    deploy_config = configuration(plan)
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
    draft_tags = []
    for package, version in plan["versions"].items():
        tag = f"{package}-v{version}"
        tags.append(tag)
        existing = subprocess.run(
            [
                "gh",
                "release",
                "view",
                tag,
                "--json",
                "targetCommitish,isDraft,isPrerelease",
            ],
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
            if data["isPrerelease"]:
                raise RuntimeError("Existing release channel does not match this plan")
            if not data["isDraft"]:
                continue
        draft_tags.append(tag)
        assets = [str(root / "release-manifest.json")]
        if package == "cli":
            assets += [str(p) for p in cli_dir.iterdir()]
        run("gh", "release", "upload", tag, *assets, "--clobber")
    # Recheck source immediately before every push, not just before potentially
    # slow artifact uploads. Preserve the exact Hive commit for deployment proof.
    hive = root / "hive"
    hive_sha = None
    if plan["images"]:
        subject = f"chore(kioku): deploy release {sha}"
        for attempt in range(3):
            if attempt:
                git("fetch", "origin", "main", cwd=hive)
                git("reset", "--hard", "origin/main", cwd=hive)
                update_hive(hive, plan, results)
            git("config", "user.name", "felipemeriga", cwd=hive)
            git(
                "config",
                "user.email",
                "felipemeriga@users.noreply.github.com",
                cwd=hive,
            )
            git("add", "kioku", cwd=hive)
            if not subprocess.run(
                ["git", "diff", "--cached", "--quiet"], cwd=hive, check=False
            ).returncode:
                assert_source_current(root, sha)
                hive_sha = existing_hive_commit(hive, subject)
                break
            git("commit", "-m", subject, cwd=hive)
            assert_source_current(root, sha)
            if (
                subprocess.run(
                    ["git", "push", "origin", "HEAD:main"], cwd=hive, check=False
                ).returncode
                == 0
            ):
                hive_sha = git("rev-parse", "HEAD", cwd=hive)
                break
        else:
            raise RuntimeError("Hive push failed; release drafts retained for retry")
        proof = wait_for_deployments(plan, hive_sha, config=deploy_config)
        manifest = json.loads((root / "release-manifest.json").read_text())
        manifest.update({"hive_commit": hive_sha, "verified_deployments": proof})
        dump(root / "release-manifest.json", manifest)
        for tag in draft_tags:
            run(
                "gh",
                "release",
                "upload",
                tag,
                str(root / "release-manifest.json"),
                "--clobber",
            )
    for tag in tags:
        run(
            "gh",
            "release",
            "edit",
            tag,
            "--draft=false",
        )
    git("config", "user.name", "felipemeriga", cwd=root)
    git("config", "user.email", "felipemeriga@users.noreply.github.com", cwd=root)
    ledger = "release/deployed-" + sha
    if not git("tag", "--list", ledger):
        git(
            "tag",
            "-a",
            ledger,
            sha,
            "-m",
            "All artifacts published and exact Hive deployments verified",
        )
    git("push", "origin", f"refs/tags/{ledger}")


if __name__ == "__main__":
    main()
