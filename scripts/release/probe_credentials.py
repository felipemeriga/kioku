"""Owner-invoked credential diagnosis; never deploys or exposes credential values."""

import base64
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.request

from deployment import NoRedirect, affected_services, configuration, fetch_deployments


def github_request(token, path, method="GET", body=None):
    request = urllib.request.Request(
        "https://api.github.com/" + path,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(
            request, timeout=20
        ) as response:
            return response.status, json.load(
                response
            ) if response.status != 204 else None
    except urllib.error.HTTPError as exc:
        return exc.code, None


def probe_hive(token, write=False):
    result = {}
    result["metadata_status"], _ = github_request(token, "repos/felipemeriga/hive")
    result["contents_status"], _ = github_request(
        token,
        "repos/felipemeriga/hive/contents/kioku/backend/docker-compose.yml?ref=main",
    )
    # Isolate Git from the source checkout and all inherited credential helpers.
    # The credential exists only in subprocess environment, never argv/files.
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("GIT_TRACE", "GIT_TRACE_CURL", "GIT_CURL_VERBOSE")
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
        git = subprocess.run(
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
    result["isolated_git_read"] = git.returncode == 0
    if write and result["contents_status"] == 200 and result["isolated_git_read"]:
        status, ref = github_request(
            token, "repos/felipemeriga/hive/git/ref/heads/main"
        )
        if status == 200:
            suffix = os.environ.get("GITHUB_RUN_ID", "")
            if not suffix.isdigit():
                raise ValueError("Write probe requires a GitHub run ID")
            name = "kioku-cd-permission-probe-" + suffix
            result["create_probe_ref_status"], _ = github_request(
                token,
                "repos/felipemeriga/hive/git/refs",
                "POST",
                {"ref": "refs/heads/" + name, "sha": ref["object"]["sha"]},
            )
            if result["create_probe_ref_status"] == 201:
                result["delete_probe_ref_status"], _ = github_request(
                    token, "repos/felipemeriga/hive/git/refs/heads/" + name, "DELETE"
                )
    return result


def main():
    hive = probe_hive(os.environ["HIVE_TOKEN"], write=True)
    print("Hive credential probe (no values): " + json.dumps(hive), flush=True)
    plan = {
        "images": [
            {"package": package} for package in ("backend", "mcp", "frontend", "mihari")
        ]
    }
    config = configuration(plan)
    for service in affected_services(plan):
        fetch_deployments(config, config["ids"][service])
    print(
        "Dokploy deployment-history access verified for all five services", flush=True
    )
    if not (
        hive.get("contents_status") == 200
        and hive.get("isolated_git_read")
        and hive.get("create_probe_ref_status") == 201
        and hive.get("delete_probe_ref_status") == 204
    ):
        raise SystemExit(
            "Hive token did not pass Contents/Git/write checks; no deployment attempted"
        )


if __name__ == "__main__":
    main()
