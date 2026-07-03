"""External drop endpoint for programmatic file ingestion."""

import hashlib

from arq import create_pool
from fastapi import APIRouter, Form, Header, HTTPException, UploadFile

from db.client import get_supabase
from services.ingestion import (
    AUDIO_EXTENSIONS,
    DOCUMENT_EXTENSIONS,
    EXTENSION_TO_TYPE,
    IMAGE_EXTENSIONS,
    check_duplicate,
    compute_content_hash,
    upload_audio_to_storage,
    upload_document_to_storage,
    upload_image_to_storage,
)
from services.queue.jobs import create_job
from services.queue.settings import _redis_settings
from services.scope import resolve_root_folder_id

router = APIRouter(prefix="/api")

MAX_IMAGE_SIZE = 10 * 1024 * 1024
MAX_AUDIO_SIZE = 25 * 1024 * 1024
MAX_DOCUMENT_SIZE = 50 * 1024 * 1024


def _resolve_user_from_api_key(api_key: str) -> tuple[str, str]:
    """Verify API key against api_keys table and return (user_id, scope_folder_id)."""
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()
    sb = get_supabase()
    result = (
        sb.table("api_keys").select("user_id, scope_folder_id").eq("key_hash", key_hash).execute()
    )
    if not result.data:
        raise HTTPException(status_code=401, detail="Invalid API key")
    row = result.data[0]
    if not row.get("scope_folder_id"):
        raise HTTPException(status_code=400, detail="API key must be scoped to a folder")
    return row["user_id"], row["scope_folder_id"]


def _find_or_create_folder(folder_path: str, user_id: str, scope_folder_id: str) -> str:
    """Resolve a folder path within a scope, creating each level as needed."""
    sb = get_supabase()
    parts = [p.strip() for p in folder_path.split("/") if p.strip()]
    if not parts:
        raise HTTPException(status_code=400, detail="Empty folder name")

    parent_id: str = scope_folder_id
    folder_id: str = scope_folder_id

    for part in parts:
        query = (
            sb.table("folders")
            .select("id")
            .eq("user_id", user_id)
            .eq("parent_id", parent_id)
            .ilike("name", part)
            .limit(1)
        )
        result = query.execute()

        if result.data:
            folder_id = result.data[0]["id"]
        else:
            row = {"name": part, "user_id": user_id, "parent_id": parent_id}
            result = sb.table("folders").insert(row).execute()
            folder_id = result.data[0]["id"]

        parent_id = folder_id

    return folder_id


@router.post("/drop")
async def drop_document(
    file: UploadFile,
    folder_name: str = Form(default=None),
    authorization: str = Header(),
):
    """Accept a file from an external app, ingest it into the RAG pipeline."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    api_key = authorization.split(" ", 1)[1]
    user_id, scope_folder_id = _resolve_user_from_api_key(api_key)

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in EXTENSION_TO_TYPE:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="File is empty")

    # Size limits
    if ext in IMAGE_EXTENSIONS and len(file_bytes) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=400, detail="Image too large. Maximum 10MB.")
    if ext in AUDIO_EXTENSIONS and len(file_bytes) > MAX_AUDIO_SIZE:
        raise HTTPException(status_code=400, detail="Audio too large. Maximum 25MB.")
    if ext in DOCUMENT_EXTENSIONS and len(file_bytes) > MAX_DOCUMENT_SIZE:
        raise HTTPException(status_code=400, detail="Document too large. Maximum 50MB.")

    # Resolve folder within scope
    folder_id = scope_folder_id  # Default to scope root
    if folder_name and folder_name.strip():
        folder_id = _find_or_create_folder(folder_name.strip(), user_id, scope_folder_id)

    # Content-hash dedup at the front door.
    content_hash = compute_content_hash(file_bytes)
    if check_duplicate(content_hash, user_id):
        raise HTTPException(status_code=409, detail="Duplicate file — already ingested")

    # Route by media kind, upload bytes to Storage.
    if ext in IMAGE_EXTENSIONS:
        storage_path = upload_image_to_storage(file_bytes, user_id, content_hash, file.filename)
        media_kind, storage_bucket = "image", "images"
    elif ext in AUDIO_EXTENSIONS:
        storage_path = upload_audio_to_storage(file_bytes, user_id, content_hash, file.filename)
        media_kind, storage_bucket = "audio", "audio"
    else:
        storage_path = upload_document_to_storage(file_bytes, user_id, content_hash, file.filename)
        media_kind, storage_bucket = "document", "documents"

    root_folder_id = resolve_root_folder_id(folder_id, user_id) if folder_id else None

    sb = get_supabase()
    job_id = create_job(
        sb,
        user_id=user_id,
        kind="drop",
        source_ref=file.filename,
        root_folder_id=root_folder_id,
    )
    pool = await create_pool(_redis_settings())
    try:
        await pool.enqueue_job(
            "ingest_document_task",
            {
                "job_id": job_id,
                "user_id": user_id,
                "folder_id": folder_id,
                "root_folder_id": root_folder_id,
                "storage_bucket": storage_bucket,
                "storage_path": storage_path,
                "filename": file.filename,
                "source_type": EXTENSION_TO_TYPE.get(ext, "text"),
                "media_kind": media_kind,
                "media_url": storage_path,
                "content_hash": content_hash,
            },
        )
    finally:
        await pool.close()

    return {
        "status": "queued",
        "filename": file.filename,
        "folder_id": folder_id,
        "job_id": job_id,
    }
