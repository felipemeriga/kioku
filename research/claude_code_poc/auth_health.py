"""Cheap native model readiness probe; never reads credential files."""

import argparse
import json
from pathlib import Path

from native import NativeRunner


def classify(row):
    text = (row.get("result") or "").lower()
    if (
        row.get("returncode") == 0
        and not row.get("is_error")
        and "HEALTH_OK" in (row.get("result") or "")
    ):
        return "healthy"
    if any(
        value in text
        for value in ["another claude code process is refreshing", "exited mid-refresh"]
    ):
        return "refresh_in_progress"
    if any(
        value in text
        for value in [
            "oauth session expired",
            "login expired",
            "not logged in",
            "please run /login",
            "authentication_failed",
            "token revoked",
        ]
    ):
        return "reauth_required"
    if any(value in text for value in ["rate limit", "usage limit", "limit reached"]):
        return "quota_wait"
    return "degraded_unknown"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    args = parser.parse_args()
    row = NativeRunner(args.runtime).call(
        "readiness-health",
        "Reply HEALTH_OK.",
        persist=False,
        timeout=45,
        thinking_tokens=0,
        system_prompt="Reply exactly to this literal health request. Do not use tools.",
    )
    result = {
        "state": classify(row),
        "elapsed_s": row["elapsed_s"],
        "call_id": row["id"],
        "returncode": row["returncode"],
    }
    print(json.dumps(result))
    raise SystemExit(0 if result["state"] == "healthy" else 1)


if __name__ == "__main__":
    main()
