#!/usr/bin/env python3
"""Release planning and narrow Hive edits. No third-party dependencies."""

import argparse
import json
import re
import subprocess
from pathlib import Path

PACKAGES = ("backend", "mcp", "frontend", "mihari", "cli")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def git(*args, cwd=None):
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def dump(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def affected(paths):
    result = set()
    for path in paths:
        if (
            path.startswith((".github/workflows/release", "scripts/release/"))
            or path == ".release/versions.json"
        ):
            result.update(PACKAGES)
        if path.startswith("backend/"):
            result.update(("backend", "mcp"))
        if path.startswith("frontend/"):
            result.add("frontend")
        if path.startswith(("cli/",)) or path == ".github/workflows/cli-native.yml":
            result.update(("cli", "mihari"))
        if path.startswith(("mihari/", "watcher/")):
            result.add("mihari")
        if path in (".dockerignore", "docker-compose.yml"):
            result.update(("backend", "mcp", "frontend", "mihari"))
    return sorted(result)


def bump(version):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"Expected stable major.minor.patch, got {version!r}")
    major, minor, patch = map(int, version.split("."))
    return f"{major}.{minor}.{patch + 1}"


def bump_packages(root, packages):
    versions = json.loads((root / ".release/versions.json").read_text())
    result = {}
    for package in packages:
        if package in ("cli", "frontend"):
            path = root / package / "package.json"
            data = json.loads(path.read_text())
            version = bump(data["version"])
            data["version"] = version
            dump(path, data)
            lock_path = root / package / "package-lock.json"
            lock = json.loads(lock_path.read_text())
            lock["version"] = version
            lock["packages"][""]["version"] = version
            dump(lock_path, lock)
            if package == "cli":
                entry = root / "cli/src/index.ts"
                updated, count = re.subn(
                    r'const VERSION = "[^"]+";',
                    f'const VERSION = "{version}";',
                    entry.read_text(),
                )
                if count != 1:
                    raise ValueError("CLI VERSION constant not found exactly once")
                entry.write_text(updated)
        elif package == "backend":
            path = root / "backend/pyproject.toml"
            text = path.read_text()
            match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
            version = bump(match[1])
            path.write_text(text[: match.start(1)] + version + text[match.end(1) :])
            lock = root / "backend/uv.lock"
            updated, count = re.subn(
                r'(\[\[package\]\]\nname = "backend"\nversion = ")[^"]+("\n)',
                rf"\g<1>{version}\2",
                lock.read_text(),
            )
            if count != 1:
                raise ValueError(
                    "Backend uv.lock project stanza not found exactly once"
                )
            lock.write_text(updated)
        else:
            version = versions[package] = bump(versions[package])
        result[package] = version
    dump(root / ".release/versions.json", versions)
    return result


def prepare(root, source):
    git("fetch", "origin", "main", "--tags", cwd=root)
    head = git("rev-parse", "HEAD", cwd=root)
    remote = git("rev-parse", "origin/main", cwd=root)
    if head != remote:
        raise ValueError("Checkout must be current origin/main")
    pending_path = root / ".release/pending.json"
    pending = json.loads(pending_path.read_text()) if pending_path.exists() else {}
    if git("tag", "--points-at", head, "release/deployed-*", cwd=root):
        return None
    if head != source:
        return pending if pending.get("source_sha") == source else None
    # Only successful Hive promotions establish a baseline. Failed releases do
    # not hide changes from the next main merge.
    tags = git(
        "tag",
        "--merged",
        head,
        "--sort=-creatordate",
        "--list",
        "release/deployed-*",
        cwd=root,
    ).splitlines()
    base = tags[0] if tags else None
    paths = (
        git("diff", "--name-only", base, head, cwd=root).splitlines() if base else []
    )
    packages = affected(paths) if base else list(PACKAGES)
    if not packages:
        return None
    versions = bump_packages(root, packages)
    cloud_dir = "mihari" if (root / "mihari/Dockerfile").exists() else "watcher"
    images = []
    for package in packages:
        if package == "cli":
            continue
        name = cloud_dir if package == "mihari" else package
        context = (
            "."
            if package == "mihari"
            else ("backend" if package in ("backend", "mcp") else "frontend")
        )
        images.append(
            {
                "package": package,
                "version": versions[package],
                "image": f"felipemeriga1/kioku-{name}",
                "context": context,
                "dockerfile": f"{cloud_dir}/Dockerfile"
                if package == "mihari"
                else f"{context}/Dockerfile" + (".mcp" if package == "mcp" else ""),
                "tag": f"{versions[package]}-{source[:12]}",
            }
        )
    plan = {
        "source_sha": source,
        "versions": versions,
        "images": images,
        "cli": "cli" in packages,
        "cloud_directory": cloud_dir,
    }
    dump(pending_path, plan)
    return plan


def update_hive(root, plan, results):
    expected = {item["package"]: item for item in plan["images"]}
    received = {item["package"]: item for item in results}
    if set(expected) != set(received) or len(results) != len(received):
        raise ValueError("Build results must match planned images exactly")
    edits = []
    for package, image in expected.items():
        item = received[package]
        if not DIGEST.fullmatch(item["digest"]) or item["image"] != image["image"]:
            raise ValueError("Unexpected image or invalid digest")
        targets = (
            ["backend", "worker"]
            if package == "backend"
            else [plan["cloud_directory"] if package == "mihari" else package]
        )
        for service in targets:
            path = root / "kioku" / service / "docker-compose.yml"
            text = path.read_text()
            # Change only the intended service image, preserving env/KMS,
            # comments, bind mounts and unrelated services byte-for-byte.
            pattern = rf"(?m)^(    image: ){re.escape(image['image'])}(?::[^\s]+|@[^\s]+)?([ \t]*)$"
            replacement = f"{image['image']}:{image['tag']}@{item['digest']}"
            updated, count = re.subn(
                pattern,
                lambda m, replacement=replacement: m[1] + replacement + m[2],
                text,
            )
            if count != 1:
                raise ValueError(
                    f"Expected one matching image in {path}; Hive topology/name needs migration first"
                )
            edits.append((path, updated))
    for path, updated in edits:
        path.write_text(updated)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--source", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("hive")
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--plan", required=True, type=Path)
    p.add_argument("--results", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        plan = prepare(Path.cwd(), args.source)
        dump(args.output, plan)
    else:
        results = [json.loads(p.read_text()) for p in args.results.glob("*.json")]
        update_hive(args.root, json.loads(args.plan.read_text()), results)


if __name__ == "__main__":
    main()
