"""Explicit capability and rollout policy for every generative operation."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskPolicy:
    profile: str = "completion"
    native_verified: bool = True
    tools: bool = False


TASK_POLICIES = {
    "query_rewrite": TaskPolicy(),
    "multi_query": TaskPolicy(),
    "contextual": TaskPolicy(),
    "image_ocr": TaskPolicy(native_verified=False),
    "text_to_sql": TaskPolicy(),
    "eval_judge": TaskPolicy(native_verified=False),
    "rag_agent": TaskPolicy(profile="chat", tools=True),
    "rag_agent_sonnet": TaskPolicy(profile="chat", tools=True),
    "folder_summary_doc": TaskPolicy(),
    "folder_summary_rollup": TaskPolicy(),
    "folder_summary_reground": TaskPolicy(),
}


def engine_for(operation: str, owner_id: str | None, *, explicit_native: bool = False) -> str:
    """Default to API; native pilots require task AND credential-owner opt in."""
    policy = TASK_POLICIES[operation]
    enabled = set(filter(None, os.getenv("TSUKAI_NATIVE_TASKS", "").split(",")))
    if operation not in enabled and not explicit_native:
        return "api"
    principal = os.getenv("TSUKAI_CREDENTIAL_OWNER_ID")
    if not principal or owner_id != principal:
        if explicit_native:
            raise PermissionError("native execution is restricted to the credential owner")
        return "api"
    if not policy.native_verified:
        raise ValueError(f"native capability unverified: {operation}")
    return "tsukai"
