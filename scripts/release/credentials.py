"""Verify the release token can read the private Hive repository."""

import base64
import os
import subprocess
import tempfile
import urllib.error
import urllib.request

from deployment import NoRedirect


def require_hive_read(token):
    request = urllib.request.Request(
        "https://api.github.com/repos/felipemeriga/hive/contents/kioku/backend/docker-compose.yml?ref=main",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(
            request, timeout=20
        ) as response:
            if response.status != 200:
                raise RuntimeError("Hive credential needs repository Contents access")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("Hive credential needs repository Contents access") from exc

    # Check Git transport without putting the token in argv or a credential file.
    env = {
        k: v
        for k, v in os.environ.items()
        if k
        not in (
            "GIT_TRACE",
            "GIT_TRACE_CURL",
            "GIT_CURL_VERBOSE",
            "GIT_ASKPASS",
            "SSH_ASKPASS",
        )
        and not k.startswith("GIT_CONFIG_")
    }
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
            "GIT_CONFIG_VALUE_0": "AUTHORIZATION: basic "
            + base64.b64encode(("x-access-token:" + token).encode()).decode(),
            "GIT_CONFIG_KEY_1": "credential.helper",
            "GIT_CONFIG_VALUE_1": "",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    with tempfile.TemporaryDirectory() as tmp:
        result = subprocess.run(
            [
                "git",
                "ls-remote",
                "https://github.com/felipemeriga/hive.git",
                "refs/heads/main",
            ],
            cwd=tmp,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    if result.returncode:
        raise RuntimeError("Hive credential cannot read the repository through Git")
