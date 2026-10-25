#!/usr/bin/env python3
"""Only reuse an immutable image digest with the exact expected OCI revision."""

import json
import re
import subprocess
import sys

DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def revision(config):
    if not isinstance(config, dict):
        raise TypeError("Invalid OCI image configuration")
    # Imagetools returns a single config for one platform, or a platform-keyed
    # map for an index. Select the actual AMD64 config, ignoring attestations.
    if "config" not in config:
        config = config.get("linux/amd64")
    if not isinstance(config, dict):
        raise TypeError("Missing AMD64 OCI configuration")
    labels = config.get("config", {}).get("Labels", {})
    return labels.get("org.opencontainers.image.revision")


def existing_digest(reference, expected_sha, inspect=None):
    inspect = subprocess.run if inspect is None else inspect
    result = inspect(
        [
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            reference,
            "--format",
            "{{json .Manifest}}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        # Authentication, throttling, and network failures must not masquerade
        # as a missing tag and cause an existing version to be overwritten.
        if re.search(
            r"manifest unknown|not found|no such manifest", result.stderr, re.IGNORECASE
        ):
            return None
        raise RuntimeError("Cannot determine whether release image already exists")
    digest = json.loads(result.stdout).get("digest")
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise ValueError("Invalid registry manifest digest")
    image = reference.rsplit(":", 1)[0]
    config = inspect(
        [
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            image + "@" + digest,
            "--format",
            "{{json .Image}}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if config.returncode:
        raise RuntimeError("Could not verify immutable image OCI revision")
    if revision(json.loads(config.stdout)) != expected_sha:
        raise ValueError(
            "Existing release image OCI revision does not match this release commit"
        )
    return digest


if __name__ == "__main__":
    found = existing_digest(sys.argv[1], sys.argv[2])
    if found:
        print("digest=" + found)
