"""Document ingestion pipeline: parse, hash, deduplicate, chunk, embed, store."""

import asyncio
import hashlib
import logging
from pathlib import Path

from storage3.exceptions import StorageApiError

from db.client import get_supabase_thread_safe as get_supabase
from services.chunker import build_contextual_header, chunk_text
from services.embeddings import embed_document
from services.metadata import extract_metadata
from services.parser import extract_from_image, parse_document, transcribe_audio
from services.scope import resolve_root_folder_id

logger = logging.getLogger(__name__)
ingestion_semaphore = asyncio.Semaphore(5)

EXTENSION_TO_TYPE = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".html": "html",
    ".htm": "html",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".text": "text",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".mp3": "audio",
    ".webm": "audio",
    ".m4a": "audio",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
AUDIO_EXTENSIONS = {".mp3", ".webm", ".m4a"}


def compute_content_hash(content: bytes) -> str:
    """Compute SHA-256 hash of raw file bytes."""
    return hashlib.sha256(content).hexdigest()


def check_duplicate(content_hash: str, user_id: str) -> bool:
    """Check if a document with this hash already exists for the user."""
    sb = get_supabase()
    result = (
        sb.table("documents")
        .select("id")
        .eq("content_hash", content_hash)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return len(result.data) > 0


def update_ingestion_status(
    status_id: str,
    stage: str,
    stage_detail: str | None = None,
    chunks_total: int | None = None,
    chunks_done: int | None = None,
    error_message: str | None = None,
    duplicate: bool | None = None,
    document_ids: list[str] | None = None,
) -> None:
    """Update the ingestion_status row for a background task."""
    sb = get_supabase()
    data: dict = {"stage": stage}
    if stage_detail is not None:
        data["stage_detail"] = stage_detail
    if chunks_total is not None:
        data["chunks_total"] = chunks_total
    if chunks_done is not None:
        data["chunks_done"] = chunks_done
    if error_message is not None:
        data["error_message"] = error_message
    if duplicate is not None:
        data["duplicate"] = duplicate
    if document_ids is not None:
        data["document_ids"] = document_ids
    sb.table("ingestion_status").update(data).eq("id", status_id).execute()


def _upload_to_bucket(bucket: str, storage_path: str, file_bytes: bytes, media_type: str) -> None:
    """Upload to a Supabase Storage bucket, overwriting if the file already exists."""
    sb = get_supabase()
    try:
        sb.storage.from_(bucket).upload(storage_path, file_bytes, {"content-type": media_type})
    except StorageApiError as exc:
        if str(exc.status) == "409":
            sb.storage.from_(bucket).update(storage_path, file_bytes, {"content-type": media_type})
        else:
            raise


def upload_image_to_storage(
    file_bytes: bytes, user_id: str, content_hash: str, filename: str
) -> str:
    """Upload raw image to Supabase Storage and return the path."""
    ext = Path(filename).suffix.lower().lstrip(".")
    storage_path = f"{user_id}/{content_hash}.{ext}"
    media_type = "image/png" if ext == "png" else "image/jpeg"
    _upload_to_bucket("images", storage_path, file_bytes, media_type)
    return storage_path


def upload_audio_to_storage(
    file_bytes: bytes, user_id: str, content_hash: str, filename: str
) -> str:
    """Upload raw audio to Supabase Storage and return the path."""
    ext = Path(filename).suffix.lower().lstrip(".")
    storage_path = f"{user_id}/{content_hash}.{ext}"
    mime_types = {"mp3": "audio/mpeg", "webm": "audio/webm", "m4a": "audio/mp4"}
    media_type = mime_types.get(ext, "audio/mpeg")
    _upload_to_bucket("audio", storage_path, file_bytes, media_type)
    return storage_path


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


def upload_document_to_storage(
    file_bytes: bytes, user_id: str, content_hash: str, filename: str
) -> str:
    """Upload raw document to Supabase Storage and return the path."""
    ext = Path(filename).suffix.lower().lstrip(".")
    storage_path = f"{user_id}/{content_hash}.{ext}"
    mime_types = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "html": "text/html",
        "htm": "text/html",
        "md": "text/markdown",
        "markdown": "text/markdown",
        "txt": "text/plain",
        "text": "text/plain",
        "json": "application/json",
        "yaml": "text/yaml",
        "yml": "text/yaml",
    }
    media_type = mime_types.get(ext, "application/octet-stream")
    _upload_to_bucket("documents", storage_path, file_bytes, media_type)
    return storage_path


def ingest_document(
    file_bytes: bytes,
    filename: str,
    user_id: str,
    folder_id: str | None = None,
    status_id: str | None = None,
) -> dict:
    """Ingest a document or image: parse, hash, deduplicate, chunk, embed, store."""

    def _update(stage: str, **kwargs: object) -> None:
        if status_id is not None:
            update_ingestion_status(status_id, stage, **kwargs)

    # Resolve root folder for scope filtering
    root_folder_id = None
    if folder_id:
        root_folder_id = resolve_root_folder_id(folder_id, user_id)

    content_hash = compute_content_hash(file_bytes)

    if check_duplicate(content_hash, user_id):
        _update("duplicate", duplicate=True)
        return {"duplicate": True, "chunks": 0, "document_ids": []}

    ext = Path(filename).suffix.lower()
    is_image = ext in IMAGE_EXTENSIONS
    is_audio = ext in AUDIO_EXTENSIONS
    is_document = ext in DOCUMENT_EXTENSIONS
    media_storage_path: str | None = None
    media_type: str | None = None  # "image" or "audio"

    # Upload media to storage before parsing
    _update("uploading", stage_detail="Uploading to storage...")
    if is_image:
        media_storage_path = upload_image_to_storage(file_bytes, user_id, content_hash, filename)
        media_type = "image"
    elif is_audio:
        media_storage_path = upload_audio_to_storage(file_bytes, user_id, content_hash, filename)
        media_type = "audio"
    elif is_document:
        media_storage_path = upload_document_to_storage(file_bytes, user_id, content_hash, filename)
        media_type = "document"

    # Parse: image via Claude Vision, audio via Whisper, documents via Docling
    _update("parsing", stage_detail="Extracting text...")
    if is_image:
        text = extract_from_image(file_bytes, filename)
    elif is_audio:
        text = transcribe_audio(file_bytes, filename)
    else:
        text = parse_document(file_bytes, filename)

    if not text.strip():
        _update("completed", chunks_total=0, stage_detail="No text extracted")
        return {"duplicate": False, "chunks": 0, "document_ids": []}

    _update("chunking", stage_detail="Splitting into chunks...")
    chunks = chunk_text(text)
    if not chunks:
        _update("completed", chunks_total=0, stage_detail="No chunks created")
        return {"duplicate": False, "chunks": 0, "document_ids": []}

    _update("chunking", chunks_total=len(chunks), stage_detail=f"{len(chunks)} chunks created")

    source_type = EXTENSION_TO_TYPE.get(ext, "text")
    sb = get_supabase()
    inserted_ids: list[str] = []

    for i, chunk in enumerate(chunks):
        _update(
            "extracting_metadata",
            chunks_done=i,
            stage_detail=f"Extracting metadata for chunk {i + 1}/{len(chunks)}",
        )
        meta = extract_metadata(chunk)

        metadata = {
            "source_filename": filename,
            "chunk_index": i,
            "total_chunks": len(chunks),
            "topic": meta["topic"],
            "keywords": meta["keywords"],
        }

        # Embed the chunk with contextual header for better retrieval
        _update(
            "embedding",
            chunks_done=i,
            stage_detail=f"Embedding chunk {i + 1}/{len(chunks)}",
        )
        chunk_with_context = f"{build_contextual_header(metadata)}\n\n{chunk}"
        embedding = embed_document(chunk_with_context)
        if media_storage_path and media_type == "image":
            metadata["image_url"] = media_storage_path
        elif media_storage_path and media_type == "audio":
            metadata["audio_url"] = media_storage_path
        elif media_storage_path and media_type == "document":
            metadata["file_url"] = media_storage_path

        _update(
            "storing",
            chunks_done=i,
            stage_detail=f"Storing chunk {i + 1}/{len(chunks)}",
        )
        row = {
            "content": chunk,
            "embedding": embedding,
            "metadata": metadata,
            "user_id": user_id,
            "source_filename": filename,
            "source_type": source_type,
            "content_hash": content_hash,
            "status": "processing",
        }
        if folder_id:
            row["folder_id"] = folder_id
        if root_folder_id:
            row["root_folder_id"] = root_folder_id

        result = sb.table("documents").insert(row).execute()
        inserted_ids.append(result.data[0]["id"])

    sb.table("documents").update({"status": "completed"}).eq("content_hash", content_hash).eq(
        "user_id", user_id
    ).execute()

    _update(
        "completed",
        chunks_done=len(inserted_ids),
        chunks_total=len(inserted_ids),
        document_ids=inserted_ids,
        stage_detail=f"Ingested {len(inserted_ids)} chunks",
    )

    return {"duplicate": False, "chunks": len(inserted_ids), "document_ids": inserted_ids}


async def run_ingestion_background(
    file_bytes: bytes,
    filename: str,
    user_id: str,
    folder_id: str | None,
    status_id: str,
) -> None:
    """Run ingestion in background with semaphore concurrency limit."""
    async with ingestion_semaphore:
        try:
            await asyncio.to_thread(
                ingest_document,
                file_bytes=file_bytes,
                filename=filename,
                user_id=user_id,
                folder_id=folder_id,
                status_id=status_id,
            )
        except Exception as exc:
            logger.exception("Background ingestion failed for %s", filename)
            try:
                update_ingestion_status(status_id, "error", error_message=str(exc)[:500])
            except Exception:
                logger.exception("Failed to update error status for %s", filename)
