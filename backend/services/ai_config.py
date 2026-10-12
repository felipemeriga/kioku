"""Per-user BYOK AI provider config: encrypted provider keys + chat model choice.

PR 1 covers only the CHAT path. Helper tasks (query rewrite, OCR, text-to-SQL,
briefings) still run on the kioku Anthropic default. Keys are KMS-encrypted via
services.crypto; raw keys never leave this module (get_config returns presence
booleans only).
"""

from __future__ import annotations

from datetime import datetime, timezone

from services.crypto import decrypt_secret, encrypt_secret

PROVIDERS = ("anthropic", "openai", "deepseek")

_KEY_COLUMN = {
    "anthropic": "anthropic_key_encrypted",
    "openai": "openai_key_encrypted",
    "deepseek": "deepseek_key_encrypted",
}

# Curated model catalog surfaced in the Settings picker. reasoning=True models
# can run the chat "deep mode" (mapped to reasoning_effort for OpenAI/DeepSeek);
# vision=True models can back the image-OCR task (used in PR 2).
MODEL_CATALOG: dict[str, list[dict]] = {
    "anthropic": [
        {
            "id": "claude-sonnet-4-6",
            "label": "Claude Sonnet 4.6",
            "reasoning": True,
            "vision": True,
        },
        {
            "id": "claude-haiku-4-5-20251001",
            "label": "Claude Haiku 4.5",
            "reasoning": True,
            "vision": True,
        },
    ],
    "openai": [
        {"id": "gpt-5", "label": "GPT-5", "reasoning": True, "vision": True},
        {"id": "gpt-4o", "label": "GPT-4o", "reasoning": False, "vision": True},
        {"id": "o4-mini", "label": "o4-mini (reasoning)", "reasoning": True, "vision": True},
    ],
    "deepseek": [
        {"id": "deepseek-chat", "label": "DeepSeek Chat (V3)", "reasoning": False, "vision": False},
        {
            "id": "deepseek-reasoner",
            "label": "DeepSeek Reasoner (R1)",
            "reasoning": True,
            "vision": False,
        },
    ],
}


def is_reasoning_model(provider: str, model: str | None) -> bool:
    """True if the model supports a reasoning/thinking mode (for deep mode)."""
    for m in MODEL_CATALOG.get(provider, []):
        if m["id"] == model:
            return bool(m["reasoning"])
    return False


def _row(sb, user_id: str) -> dict | None:
    rows = (
        sb.table("user_ai_config").select("*").eq("user_id", user_id).limit(1).execute().data
    ) or []
    return rows[0] if rows else None


def get_config(sb, user_id: str) -> dict:
    """Masked config for the Settings UI — key PRESENCE only, never raw keys."""
    row = _row(sb, user_id) or {}
    return {
        "keys": {p: bool(row.get(_KEY_COLUMN[p])) for p in PROVIDERS},
        "chat_provider": row.get("chat_provider"),
        "chat_model": row.get("chat_model"),
        "catalog": MODEL_CATALOG,
    }


def _upsert(sb, user_id: str, patch: dict) -> None:
    patch = {
        **patch,
        "user_id": user_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    sb.table("user_ai_config").upsert(patch, on_conflict="user_id").execute()


def set_provider_key(sb, user_id: str, provider: str, key: str) -> None:
    """Store (or clear, if key is empty) a provider's API key, KMS-encrypted."""
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    col = _KEY_COLUMN[provider]
    value = encrypt_secret(key) if key else None
    _upsert(sb, user_id, {col: value})


def set_chat_model(sb, user_id: str, provider: str, model: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    _upsert(sb, user_id, {"chat_provider": provider, "chat_model": model})


def resolve_chat(sb, user_id: str) -> dict:
    """Resolve which provider/model/key to use for this user's chat turn.

    BYOK only when the user chose a provider AND has a key for it. Otherwise fall
    back to anthropic with api_key=None, meaning: use the existing kioku Anthropic
    env path (do NOT surface kioku's key here)."""
    row = _row(sb, user_id)
    if row:
        provider = row.get("chat_provider")
        model = row.get("chat_model")
        if provider in PROVIDERS and model:
            enc = row.get(_KEY_COLUMN[provider])
            if enc:
                return {"provider": provider, "model": model, "api_key": decrypt_secret(enc)}
    return {"provider": "anthropic", "model": None, "api_key": None}
