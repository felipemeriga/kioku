"""Retest observed exact-token misses without altering historical soak evidence."""

import json
from pathlib import Path

from native import NativeRunner


def main():
    root = Path("/private/tmp/kioku-claude-poc-runtime/history-quality")
    runner = NativeRunner(root)
    checks = []
    for custom in (False, True):
        for index in range(4):
            token = f"POC-invoice-worker-{index}-9c56006d"
            prompt = (
                f"Conversation history:\nUser: Remember {token}.\n"
                "Assistant: Acknowledged.\nUser: What exact token? Reply only the token."
            )
            row = runner.call(
                "opaque-custom" if custom else "opaque-default",
                prompt,
                persist=False,
                system_prompt=(
                    "You are Kioku, a grounded repository assistant. The user supplies "
                    "prior conversation messages as context. Answer their latest question "
                    "using that context. Preserve exact identifiers, including prefixes. "
                    "Do not claim tool execution or infer unsupported facts."
                    if custom
                    else None
                ),
            )
            checks.append(
                {
                    "custom_system": custom,
                    "case": index,
                    "exact_recall": token in (row["result"] or ""),
                    "result": row["result"],
                    "call_id": row["id"],
                }
            )
    (root / "checks.json").write_text(json.dumps(checks, indent=2))
    print(json.dumps(checks, indent=2), flush=True)


if __name__ == "__main__":
    main()
