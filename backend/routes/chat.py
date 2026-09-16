from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from auth import get_current_user
from routes._validation import require_uuid
from services.rag import stream_rag_response
from services.scope import validate_scope_folder

router = APIRouter(prefix="/api")


class ChatRequest(BaseModel):
    conversation_id: str
    content: str
    topic: str | None = None
    keyword: str | None = None
    fast_mode: bool = False
    # RAG scope: restrict retrieval to a folder subtree and/or one document.
    scope_folder_id: str | None = None
    scope_filename: str | None = None


@router.post("/chat")
async def chat(request: ChatRequest, user_id: str = Depends(get_current_user)):
    # Validate before opening the stream: a malformed conversation_id reaches
    # the uuid column in stream_rag_response and raises 22P02, which crashes the
    # generator (client gets a silent empty stream + a server-side traceback).
    require_uuid(request.conversation_id, "Conversation not found")
    if request.scope_folder_id:
        require_uuid(request.scope_folder_id, "Scope folder not found")
        validate_scope_folder(request.scope_folder_id, user_id)

    def event_generator():
        yield from stream_rag_response(
            conversation_id=request.conversation_id,
            user_message=request.content,
            user_id=user_id,
            topic=request.topic,
            keyword=request.keyword,
            fast_mode=request.fast_mode,
            scope_folder_id=request.scope_folder_id,
            scope_filename=request.scope_filename,
        )

    return StreamingResponse(event_generator(), media_type="text/event-stream")
