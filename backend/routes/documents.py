"""Document upload, list, delete, and move endpoints."""

from datetime import datetime, timedelta, timezone

from arq import create_pool
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from auth import get_current_user
from db.client import get_supabase
from services.ingestion import (
    EXTENSION_TO_TYPE,
    check_duplicate,
    compute_content_hash,
    upload_audio_to_storage,
    upload_document_to_storage,
    upload_image_to_storage,
)
from services.queue.jobs import create_job
from services.queue.settings import _redis_settings
from services.scope import resolve_root_folder_id

router = APIRouter(prefix="/api/documents")


ALLOWED_EXTENSIONS = {
    ".txt",
    ".text",
    ".md",
    ".markdown",
    ".pdf",
    ".docx",
    ".html",
    ".htm",
    ".json",
    ".yaml",
    ".yml",
    ".png",
    ".jpg",
    ".jpeg",
    ".mp3",
    ".webm",
    ".m4a",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
AUDIO_EXTENSIONS = {".mp3", ".webm", ".m4a"}
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_AUDIO_SIZE = 25 * 1024 * 1024  # 25MB
DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".html",
    ".htm",
    ".md",
    ".markdown",
    ".txt",
    ".text",
    ".json",
    ".yaml",
    ".yml",
}
MAX_DOCUMENT_SIZE = 50 * 1024 * 1024  # 50MB


@router.post("/upload")
async def upload_document(
    file: UploadFile,
    folder_id: str | None = None,
    user_id: str = Depends(get_current_user),
):
    """Upload a document for background ingestion. Returns task_id immediately."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. "
            f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="File is empty")

    if ext in IMAGE_EXTENSIONS and len(file_bytes) > MAX_IMAGE_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Image too large ({len(file_bytes) // 1024 // 1024}MB). Maximum size is 10MB.",
        )

    if ext in AUDIO_EXTENSIONS and len(file_bytes) > MAX_AUDIO_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Audio too large ({len(file_bytes) // 1024 // 1024}MB). Maximum size is 25MB.",
        )

    if ext in DOCUMENT_EXTENSIONS and len(file_bytes) > MAX_DOCUMENT_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Document too large ({len(file_bytes) // 1024 // 1024}MB). Max is 50MB.",
        )

    sb = get_supabase()

    # Content-hash dedup at the front door — no work queued if we already have it.
    content_hash = compute_content_hash(file_bytes)
    if check_duplicate(content_hash, user_id):
        return {"task_id": None, "duplicate": True, "chunks": 0}

    # Route by media kind, upload bytes to Storage.
    if ext in IMAGE_EXTENSIONS:
        storage_path = upload_image_to_storage(file_bytes, user_id, content_hash, file.filename)
        media_kind, storage_bucket = "image", "images"
        media_url = storage_path
    elif ext in AUDIO_EXTENSIONS:
        storage_path = upload_audio_to_storage(file_bytes, user_id, content_hash, file.filename)
        media_kind, storage_bucket = "audio", "audio"
        media_url = storage_path
    else:
        storage_path = upload_document_to_storage(file_bytes, user_id, content_hash, file.filename)
        media_kind, storage_bucket = "document", "documents"
        media_url = storage_path

    # Resolve root folder for scope filtering
    root_folder_id = resolve_root_folder_id(folder_id, user_id) if folder_id else None

    # Create ingestion_jobs row and enqueue the task.
    # source_ref = filename (readable in UI). content-hash dedup upstream
    # prevents concurrent same-file uploads from colliding on this constraint.
    job_id = create_job(
        sb,
        user_id=user_id,
        kind="upload",
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
                "media_url": media_url,
                "content_hash": content_hash,
            },
        )
    finally:
        await pool.close()

    return {"task_id": job_id, "duplicate": False}


@router.get("/ingestion-status")
async def get_ingestion_status(user_id: str = Depends(get_current_user)):
    """Return active + recently-finished upload jobs, mapped to the legacy
    ingestion_status shape so the frontend needs no changes."""
    sb = get_supabase()
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()

    active = (
        sb.table("ingestion_jobs")
        .select("*")
        .eq("user_id", user_id)
        .eq("kind", "upload")
        .in_("status", ["queued", "running"])
        .execute()
    ).data or []

    finished = (
        sb.table("ingestion_jobs")
        .select("*")
        .eq("user_id", user_id)
        .eq("kind", "upload")
        .in_("status", ["completed", "failed"])
        .gte("updated_at", cutoff)
        .execute()
    ).data or []

    def _shape(job: dict) -> dict:
        status = job.get("status") or "queued"
        stage_map = {
            "queued": "uploading",
            "running": job.get("current_step") or "processing",
            "completed": "completed",
            "failed": "error",
        }
        total = job.get("total_batches") or 0
        done = job.get("processed_batches") or 0
        return {
            "id": job["id"],
            "user_id": job["user_id"],
            "filename": job.get("source_ref") or "unknown",
            "folder_id": job.get("root_folder_id"),
            "stage": stage_map.get(status, status),
            "stage_detail": (job.get("error") if status == "failed" else None),
            "chunks_total": total,
            "chunks_done": done,
            "created_at": job.get("created_at"),
            "updated_at": job.get("updated_at"),
        }

    tasks = [_shape(j) for j in active + finished]
    tasks.sort(key=lambda t: t["created_at"])
    return tasks


@router.get("")
async def list_documents(
    folder_id: str | None = None,
    user_id: str = Depends(get_current_user),
):
    """List user's uploaded documents, grouped by source filename, optionally filtered by folder."""
    sb = get_supabase()
    query = (
        sb.table("documents")
        .select("id, source_filename, source_type, metadata, status, created_at, folder_id")
        .eq("user_id", user_id)
    )

    if folder_id:
        query = query.eq("folder_id", folder_id)
    else:
        query = query.is_("folder_id", "null")

    result = query.order("created_at", desc=True).execute()

    # Group by source_filename
    files: dict[str, dict] = {}
    for doc in result.data:
        fname = doc.get("source_filename") or "unknown"
        if fname not in files:
            meta = doc.get("metadata") or {}
            has_file = bool(meta.get("file_url") or meta.get("image_url") or meta.get("audio_url"))
            files[fname] = {
                "source_filename": fname,
                "source_type": doc.get("source_type", "text"),
                "has_file": has_file,
                "chunks": 0,
                "status": doc.get("status", "completed"),
                "created_at": doc["created_at"],
                "folder_id": doc.get("folder_id"),
            }
        files[fname]["chunks"] += 1
        # If any chunk is processing or failed, reflect that
        if doc.get("status") == "processing":
            files[fname]["status"] = "processing"
        elif doc.get("status") == "failed" and files[fname]["status"] != "processing":
            files[fname]["status"] = "failed"

    return list(files.values())


def _infer_viewable_as(filename: str, source_type: str | None, metadata: dict) -> str:
    """Renderer hint for the frontend: 'markdown' | 'image' | 'pdf' |
    'audio' | 'video' | 'code' | 'text'."""
    name = filename.lower()
    if source_type in ("github_commit", "github_pr", "github_issue"):
        return "markdown"
    if name.endswith((".md", ".markdown")):
        return "markdown"
    if name.endswith((".htm", ".html")):
        return "markdown"
    if name.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")):
        return "image"
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith((".mp3", ".m4a", ".wav", ".ogg", ".flac")):
        return "audio"
    if name.endswith((".mp4", ".webm", ".mov")):
        return "video"
    if name.endswith((".json", ".yaml", ".yml", ".toml")):
        return "code"
    if name.endswith((".py", ".ts", ".tsx", ".js", ".jsx", ".rs", ".go", ".java", ".c", ".cpp", ".sh", ".sql")):
        return "code"
    return "text"


_INLINE_URL_TTL_S = 300  # 5 min — long enough to render + interact, short
                          # enough that a leaked screenshot expires fast.


def _signed_view_url(sb, metadata: dict) -> tuple[str | None, str | None]:
    """(signed_url, bucket) for inline viewing. No `download` option so the
    browser embeds instead of forcing a save. TTL kept short because the
    URL is a bearer token — anyone with it can view until expiry.
    """
    file_path = metadata.get("file_url") or metadata.get("image_url") or metadata.get("audio_url")
    if not file_path:
        return None, None
    if metadata.get("image_url"):
        bucket = "images"
    elif metadata.get("audio_url"):
        bucket = "audio"
    else:
        bucket = "documents"
    try:
        signed = sb.storage.from_(bucket).create_signed_url(file_path, _INLINE_URL_TTL_S)
        return signed.get("signedURL") or signed.get("signed_url"), bucket
    except Exception:  # noqa: BLE001
        return None, bucket


@router.get("/{filename}/content")
async def get_document_content(
    filename: str,
    folder_id: str | None = None,
    user_id: str = Depends(get_current_user),
):
    """Full text plus a viewable_as hint and, when the original binary is
    stored (image, PDF, audio…), a short-lived signed URL the browser can
    embed in an <img> / <iframe> / <audio> tag inline.
    """
    sb = get_supabase()
    q = (
        sb.table("documents")
        .select("content, chunk_index, source_type, metadata, folder_id, status, created_at")
        .eq("source_filename", filename)
        .eq("user_id", user_id)
    )
    if folder_id:
        q = q.eq("folder_id", folder_id)
    r = q.order("chunk_index").execute()
    if not r.data:
        raise HTTPException(status_code=404, detail="Document not found")

    rows = r.data
    content = "\n\n".join((c.get("content") or "") for c in rows)
    first = rows[0]
    metadata = first.get("metadata") or {}
    view_url, bucket = _signed_view_url(sb, metadata)
    viewable_as = _infer_viewable_as(filename, first.get("source_type"), metadata)
    return {
        "source_filename": filename,
        "source_type": first.get("source_type"),
        "metadata": metadata,
        "chunk_count": len(rows),
        "folder_id": first.get("folder_id"),
        "status": first.get("status"),
        "created_at": first.get("created_at"),
        "content": content,
        "viewable_as": viewable_as,
        "file_url": view_url,
        "bucket": bucket,
    }


@router.get("/{filename}/download")
async def download_document(filename: str, user_id: str = Depends(get_current_user)):
    """Generate a signed download URL for the original uploaded file."""
    sb = get_supabase()

    docs = (
        sb.table("documents")
        .select("metadata, source_type")
        .eq("source_filename", filename)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not docs.data:
        raise HTTPException(status_code=404, detail="Document not found")

    meta = docs.data[0].get("metadata") or {}
    file_url = meta.get("file_url") or meta.get("image_url") or meta.get("audio_url")
    if not file_url:
        raise HTTPException(status_code=404, detail="Original file not available")

    if meta.get("image_url"):
        bucket = "images"
    elif meta.get("audio_url"):
        bucket = "audio"
    else:
        bucket = "documents"

    signed = sb.storage.from_(bucket).create_signed_url(
        file_url, 300, options={"download": filename}
    )
    return {"url": signed["signedURL"]}


@router.get("/filters")
async def get_filters(user_id: str = Depends(get_current_user)):
    """Return available topics and keywords for the user's documents."""
    sb = get_supabase()
    result = (
        sb.table("documents")
        .select("metadata")
        .or_(f"user_id.eq.{user_id},user_id.is.null")
        .not_.is_("metadata", "null")
        .execute()
    )

    topics: set[str] = set()
    keywords: set[str] = set()
    for doc in result.data:
        meta = doc.get("metadata") or {}
        if meta.get("topic") and meta["topic"] != "unknown":
            topics.add(meta["topic"])
        for kw in meta.get("keywords", []):
            keywords.add(kw)

    return {
        "topics": sorted(topics),
        "keywords": sorted(keywords),
    }


class MoveDocumentRequest(BaseModel):
    folder_id: str | None = None


@router.patch("/{filename}/move")
async def move_document(
    filename: str,
    body: MoveDocumentRequest,
    user_id: str = Depends(get_current_user),
):
    """Move all chunks of a document to a different folder (or root if folder_id is null)."""
    sb = get_supabase()

    # Verify target folder belongs to user if specified
    if body.folder_id:
        folder = (
            sb.table("folders")
            .select("id")
            .eq("id", body.folder_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not folder.data:
            raise HTTPException(status_code=404, detail="Target folder not found")

    root_folder_id = None
    if body.folder_id:
        root_folder_id = resolve_root_folder_id(body.folder_id, user_id)

    update_data = {"folder_id": body.folder_id, "root_folder_id": root_folder_id}
    sb.table("documents").update(update_data).eq("source_filename", filename).eq(
        "user_id", user_id
    ).execute()
    return {"ok": True}


@router.delete("/{filename}")
async def delete_document(filename: str, user_id: str = Depends(get_current_user)):
    """Delete all chunks for a given filename belonging to the user."""
    sb = get_supabase()

    # Check if document has stored images to clean up
    docs = (
        sb.table("documents")
        .select("metadata")
        .eq("source_filename", filename)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    meta = (docs.data[0].get("metadata") or {}) if docs.data else {}
    image_url = meta.get("image_url")
    audio_url = meta.get("audio_url")
    file_url = meta.get("file_url")

    # Delete document chunks
    sb.table("documents").delete().eq("source_filename", filename).eq("user_id", user_id).execute()

    # Delete media from storage if it exists
    try:
        if image_url:
            sb.storage.from_("images").remove([image_url])
        if audio_url:
            sb.storage.from_("audio").remove([audio_url])
        if file_url:
            sb.storage.from_("documents").remove([file_url])
    except Exception:
        pass  # Non-critical: storage cleanup is best-effort

    return {"ok": True}
