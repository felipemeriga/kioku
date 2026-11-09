"""Owner-scoped metadata catalog; never accepts arbitrary provider model IDs."""

import httpx
from fastapi import HTTPException

from services.ai.facade import client_for
from services.ai.registry import engine_for
from services.ai.scope import ExecutionScope
from services.llm import MODEL_FOR_TASK, Task


def chat_operation(model: str, owner_id: str) -> str:
    if model in {"haiku", "sonnet"}:
        return "rag_agent_sonnet" if model == "sonnet" else "rag_agent"
    for operation in ("rag_agent", "rag_agent_sonnet"):
        if engine_for(operation, owner_id) == "tsukai":
            return operation
    raise HTTPException(422, "Choose Haiku or Sonnet for API chat")


def native_enabled(owner_id: str) -> bool:
    return any(
        engine_for(operation, owner_id) == "tsukai"
        for operation in ("rag_agent", "rag_agent_sonnet")
    )


def chat_models(owner_id: str) -> dict:
    if not native_enabled(owner_id):
        return {
            "engine": "api",
            "models": [],
            "request_controls": {"reasoning_effort": ["low", "medium", "high"]},
        }
    client = client_for(ExecutionScope(owner_id), "runtime.models.read", None)
    try:
        catalog = client.models()
        if (
            not isinstance(catalog, dict)
            or catalog.get("schema_version") != 1
            or not isinstance(catalog.get("models"), list)
        ):
            raise ValueError("Invalid catalog")
        rows = []
        for row in catalog["models"]:
            if not isinstance(row, dict) or not all(
                isinstance(row.get(key), str) and row[key]
                for key in ("value", "resolvedModel", "displayName")
            ):
                raise ValueError("Invalid catalog row")
            if not all(
                isinstance(row.get(key), bool) for key in ("requires_usage_credits", "selectable")
            ):
                raise ValueError("Invalid model eligibility")
            levels = row.get("supportedEffortLevels")
            if levels is not None and (
                not isinstance(levels, list) or any(not isinstance(level, str) for level in levels)
            ):
                raise ValueError("Invalid effort capabilities")
            rows.append(
                {
                    key: row.get(key)
                    for key in (
                        "value",
                        "resolvedModel",
                        "displayName",
                        "description",
                        "requires_usage_credits",
                        "selectable",
                        "supportedEffortLevels",
                        "supportsEffort",
                    )
                }
            )
        return {
            "engine": "tsukai",
            "request_controls": catalog.get("request_controls", {}),
            "models": rows,
            "cli_version": catalog.get("cli_version"),
            "fetched_at": catalog.get("fetched_at"),
            "stale": catalog.get("stale", False),
        }
    except (httpx.HTTPError, RuntimeError, ValueError, KeyError, TypeError):
        raise HTTPException(503, "Native model catalog is unavailable. Please try again.") from None
    finally:
        client.close()


def resolve_native_model(model: str, owner_id: str, reasoning_effort: str | None = None) -> str:
    try:
        catalog = chat_models(owner_id)
    except HTTPException:
        # Retain the previously supported fixed legacy routes only. New model
        # IDs require a successful authenticated catalog lookup, never guessing.
        if reasoning_effort is None and model in {"haiku", "sonnet"}:
            return MODEL_FOR_TASK[Task.RAG_AGENT_SONNET if model == "sonnet" else Task.RAG_AGENT]
        raise
    controls = catalog.get("request_controls") or {}
    if reasoning_effort is not None and reasoning_effort not in controls.get(
        "reasoning_effort", []
    ):
        raise HTTPException(503, "Reasoning controls are updating. Please try again shortly.")
    if catalog.get("stale"):
        if reasoning_effort is None and model in {"haiku", "sonnet"}:
            return MODEL_FOR_TASK[Task.RAG_AGENT_SONNET if model == "sonnet" else Task.RAG_AGENT]
        raise HTTPException(503, "Refresh the native model catalog before choosing this model")
    for row in catalog["models"]:
        if model == row["resolvedModel"] or (
            model in {"haiku", "sonnet"} and model == row["value"]
        ):
            if row["requires_usage_credits"] is not False:
                raise HTTPException(
                    422, "This model requires extra usage credits and is unavailable"
                )
            if row["selectable"] is not True:
                raise HTTPException(422, "This subscription model is currently unavailable")
            levels = row.get("supportedEffortLevels")
            if (
                reasoning_effort is not None
                and isinstance(levels, list)
                and reasoning_effort not in levels
            ):
                raise HTTPException(422, "Choose a supported reasoning effort for this model")
            return row["resolvedModel"]
    raise HTTPException(422, "Choose an available subscription model from the model picker")
