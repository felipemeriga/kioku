"""Git transport policy shared by the API and the separately packaged Mihari worker."""

import os
import re
from urllib.parse import urlsplit

DEFAULT_HOSTS = frozenset({"github.com", "gitlab.com", "bitbucket.org"})
GIT_OPTIONS = [
    "-c",
    "protocol.allow=never",
    "-c",
    "protocol.ssh.allow=always",
    "-c",
    "protocol.https.allow=always",
    "-c",
    "http.followRedirects=false",
    "-c",
    "submodule.recurse=false",
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "credential.helper=",
]
GIT_ENV = {
    "GIT_ALLOW_PROTOCOL": "ssh:https",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
}


def validate_git_remote(value: str) -> str:
    if not isinstance(value, str) or not 8 <= len(value) <= 500:
        raise ValueError("Invalid Git remote")
    allowed = DEFAULT_HOSTS | {
        host.strip().lower()
        for host in os.environ.get("MIHARI_ALLOWED_GIT_HOSTS", "").split(",")
        if host.strip()
    }
    if "://" in value:
        parts = urlsplit(value)
        if parts.scheme not in {"ssh", "https"} or parts.password or parts.query or parts.fragment:
            raise ValueError("Only approved SSH and HTTPS Git remotes are supported")
        if parts.scheme == "https" and parts.username is not None:
            raise ValueError("Git credentials must not be embedded in URLs")
        if (
            parts.scheme == "ssh"
            and parts.username is not None
            and not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", parts.username)
        ):
            raise ValueError("Invalid Git SSH user")
        host, path = parts.hostname, parts.path.removeprefix("/")
        if parts.port is not None and not 1 <= parts.port <= 65535:
            raise ValueError("Invalid Git port")
    else:
        match = re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*@([A-Za-z0-9.-]+):(.+)", value)
        if not match:
            raise ValueError("Local paths and Git remote helpers are not supported")
        host, path = match.groups()
    if not host or host.lower() not in allowed:
        raise ValueError("Git host is not approved for Mihari")
    if any(ord(char) <= 32 or ord(char) == 127 for char in value):
        raise ValueError("Invalid Git remote characters")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+", path) or any(
        part in {".", ".."} or part.startswith("-") for part in path.split("/")
    ):
        raise ValueError("Invalid Git repository path")
    return value


def validate_git_branch(value: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 200
        or value.startswith(("-", "/"))
        or value.endswith(("/", "."))
        or value in {"@", "HEAD"}
        or ".." in value
        or "@{" in value
        or re.search(r"[\s\x00-\x1f\x7f~^:?*\[\\]", value)
        or any(
            not part or part.startswith(".") or part.endswith(".lock") for part in value.split("/")
        )
    ):
        raise ValueError("Invalid Git branch")
    return value
