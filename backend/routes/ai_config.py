"""BYOK AI provider config: provider API keys + chat model selection.

Keys are write-only from the client's perspective — GET returns presence
booleans, never the raw key. All queries are scoped to the authenticated user.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from db.client import get_supabase
from services.ai_config import (
    PROVIDERS,
    get_config,
    set_chat_model,
    set_provider_key,
)

router = APIRouter(prefix="/api/ai-config")


class ProviderKeyRequest(BaseModel):
    provider: str
    key: str  # "" clears the stored key


class ChatModelRequest(BaseModel):
    provider: str
    model: str


@router.get("")
async def read_ai_config(user_id: str = Depends(get_current_user)):
    return get_config(get_supabase(), user_id)


@router.put("/key")
async def put_provider_key(body: ProviderKeyRequest, user_id: str = Depends(get_current_user)):
    if body.provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {body.provider}")
    set_provider_key(get_supabase(), user_id, body.provider, body.key)
    return {"ok": True}


@router.put("/chat-model")
async def put_chat_model(body: ChatModelRequest, user_id: str = Depends(get_current_user)):
    if body.provider not in PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {body.provider}")
    set_chat_model(get_supabase(), user_id, body.provider, body.model)
    return {"ok": True}
