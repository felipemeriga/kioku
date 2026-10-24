#!/usr/bin/env python3
"""Smoke compiled commands without installing hooks or a persistent service."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

binary = str(Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory() as tmp:
    env = {
        **os.environ,
        "HOME": tmp,
        "USERPROFILE": tmp,
        "XDG_CONFIG_HOME": tmp,
        "KIOKU_NO_UPDATE_CHECK": "1",
    }
    for command in (["--version"], ["--help"], ["session-start"]):
        subprocess.run([binary, *command], cwd=tmp, env=env, check=True, timeout=15)
    # Once Manabi is merged, ensure its dedicated entry exists and rejects an
    # invalid config cleanly rather than crashing on embedded filesystem paths.
    if Path("cli/src/lib/manabi.ts").exists():
        config = Path(tmp) / "invalid-manabi.json"
        config.write_text(json.dumps({}))
        result = subprocess.run(
            [binary, "internal-manabi-run", str(config)],
            cwd=tmp,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if (
            "unknown command" in result.stderr.lower()
            or "cannot find module" in result.stderr.lower()
        ):
            raise RuntimeError(result.stderr)
        if result.returncode == 0:
            raise RuntimeError("Invalid daemon config unexpectedly accepted")
