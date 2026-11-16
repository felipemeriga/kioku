"""Paths that must never be promoted from a checkout into searchable code."""


def is_indexable_source_file(path: str | None) -> bool:
    if not isinstance(path, str) or not path or path.startswith(("/", "\\")):
        return False
    parts = path.replace("\\", "/").lower().split("/")
    return not any(
        not part
        or part
        in {
            ".",
            "..",
            ".git",
            ".claude",
            ".codex",
            ".ssh",
            ".aws",
            ".mcp.json",
            ".npmrc",
            ".pypirc",
            ".netrc",
        }
        or part.startswith(".env")
        or ":" in part
        for part in parts
    )
