"""Storage + dedup helpers for uploaded documents.

The actual ingestion pipeline (parse → chunk → embed → store) lives in
`services/queue/tasks.py::ingest_document_task`, executed by the arq worker.
This module keeps only the helpers that both the HTTP route and the queue
task rely on.
"""

import hashlib
import logging
from pathlib import Path

from storage3.exceptions import StorageApiError

from db.client import get_supabase_thread_safe as get_supabase

logger = logging.getLogger(__name__)

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


def compute_content_hash(content: bytes) -> str:
    """SHA-256 of raw file bytes."""
    return hashlib.sha256(content).hexdigest()


def check_duplicate(content_hash: str, user_id: str) -> bool:
    """Return True if a document with this hash already exists for the user."""
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


def _upload_to_bucket(bucket: str, storage_path: str, file_bytes: bytes, media_type: str) -> None:
    """Upload to a Supabase Storage bucket, overwriting on 409."""
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
    ext = Path(filename).suffix.lower().lstrip(".")
    storage_path = f"{user_id}/{content_hash}.{ext}"
    media_type = "image/png" if ext == "png" else "image/jpeg"
    _upload_to_bucket("images", storage_path, file_bytes, media_type)
    return storage_path


def upload_audio_to_storage(
    file_bytes: bytes, user_id: str, content_hash: str, filename: str
) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    storage_path = f"{user_id}/{content_hash}.{ext}"
    mime_types = {"mp3": "audio/mpeg", "webm": "audio/webm", "m4a": "audio/mp4"}
    media_type = mime_types.get(ext, "audio/mpeg")
    _upload_to_bucket("audio", storage_path, file_bytes, media_type)
    return storage_path


def upload_document_to_storage(
    file_bytes: bytes, user_id: str, content_hash: str, filename: str
) -> str:
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
) -> dict:
    """Synchronous ingestion — used only by eval/runner.py against local Supabase.

    Production ingestion goes through the arq queue via
    services/queue/tasks.py::ingest_document_task. This helper mirrors the same
    parse → chunk → embed_batch → insert steps but blocks the caller so eval
    scripts can drive it without a worker running.
    """
    from services.chunker import chunk_text
    from services.embeddings import embed_batch
    from services.metadata import extract_metadata
    from services.parser import extract_from_image, parse_document, transcribe_audio
    from services.scope import resolve_root_folder_id

    root_folder_id = resolve_root_folder_id(folder_id, user_id) if folder_id else None
    content_hash = compute_content_hash(file_bytes)
    if check_duplicate(content_hash, user_id):
        return {"duplicate": True, "chunks": 0, "document_ids": []}

    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        text = extract_from_image(file_bytes, filename)
    elif ext in AUDIO_EXTENSIONS:
        text = transcribe_audio(file_bytes, filename)
    else:
        text = parse_document(file_bytes, filename)

    if not text or not text.strip():
        return {"duplicate": False, "chunks": 0, "document_ids": []}

    chunks = chunk_text(text)
    if not chunks:
        return {"duplicate": False, "chunks": 0, "document_ids": []}

    source_type = EXTENSION_TO_TYPE.get(ext, "text")
    embeddings = embed_batch(chunks)
    sb = get_supabase()
    ids: list[str] = []
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
        meta = extract_metadata(chunk) or {}
        row = {
            "user_id": user_id,
            "content": chunk,
            "embedding": embedding,
            "metadata": {
                **meta,
                "source_filename": filename,
                "chunk_index": i,
                "total_chunks": len(chunks),
            },
            "source_filename": filename,
            "source_type": source_type,
            "content_hash": content_hash,
            "chunk_index": i,
            "status": "completed",
        }
        if folder_id:
            row["folder_id"] = folder_id
        if root_folder_id:
            row["root_folder_id"] = root_folder_id
        result = sb.table("documents").insert(row).execute()
        ids.append(result.data[0]["id"])

    return {"duplicate": False, "chunks": len(ids), "document_ids": ids}
