"""Explicit capability and rollout policy for every generative operation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TaskPolicy:
    profile: str = "completion"
    native_verified: bool = True
    tools: bool = False
    output: str = "text"


TASK_POLICIES = {
    "query_rewrite": TaskPolicy(),
    "multi_query": TaskPolicy(output="queries"),
    "contextual": TaskPolicy(),
    "image_ocr": TaskPolicy(),
    "text_to_sql": TaskPolicy(),
    "eval_judge": TaskPolicy(),
    "rag_agent": TaskPolicy(profile="chat", tools=True),
    "rag_agent_sonnet": TaskPolicy(profile="chat", tools=True),
    "folder_summary_doc": TaskPolicy(),
    "folder_summary_rollup": TaskPolicy(output="json"),
    "folder_summary_reground": TaskPolicy(output="json"),
}


def engine_for(operation: str, owner_id: str | None, *, explicit_native: bool = False) -> str:
    """All authenticated owners share the deployment's subscription execution pool.

    Funding identity is not data authority: capabilities still bind the actual
    caller, tenant, folders and request digest. No operation may fall back to API.
    """
    policy = TASK_POLICIES[operation]
    if not owner_id:
        raise PermissionError("subscription execution requires authenticated owner scope")
    if not policy.native_verified:
        raise ValueError(f"native capability unverified: {operation}")
    return "tsukai"
