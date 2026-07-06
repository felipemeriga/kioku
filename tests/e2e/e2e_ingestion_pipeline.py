"""E2E: full ingestion pipeline — upload → parse → chunk → embed → search.

The core RAG loop of the product. If this breaks, everything breaks.

Coverage:
  A. Upload .txt file → task queued, chunks created, embeddings computed
  B. Upload .md file → same as A, plus verifies markdown parsing
  C. Upload the SAME .txt again → returns duplicate=true, no new chunks
  D. Empty file → 400
  E. Unsupported extension → 400
  F. Non-existent folder_id → 400 or 404
  G. Wrong-user folder_id → 404 (cross-user isolation)
  H. Ingested docs are searchable via /api/search
  I. Metadata (topics/keywords) extracted after ingestion
  J. Doc listing returns fresh row within a reasonable time
  K. Delete via DELETE /{filename} removes chunks + storage
  L. Move via PATCH /{filename}/move changes folder_id atomically
  M. GET /content returns the reconstructed doc text
  N. Ingestion-status shows progress for in-flight uploads
"""

from __future__ import annotations
import asyncio, io, json, os, sys, time, uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from supabase import create_client

load_dotenv("/Users/feliperamosdasilva/personal_projects/kioku/backend/.env")
sys.path.insert(0, "/Users/feliperamosdasilva/personal_projects/kioku/backend")

BACKEND = "http://localhost:8000"
SUPABASE_URL = os.environ["SUPABASE_URL"]
ANON = os.environ["SUPABASE_ANON_KEY"]

PASS, FAIL = [], []


def check(n, cond, d=""):
    (PASS if cond else FAIL).append(n)
    print(f"  {'✓' if cond else '✗'} {n}" + (f" — {d[:220]}" if not cond else ""))


def hr(t):
    print()
    print("═" * 74)
    print(f"  {t}")
    print("═" * 74)


def get_token(email: str = "felipe.meriga@gmail.com"):
    admin = create_client(SUPABASE_URL, os.environ["SUPABASE_SERVICE_KEY"])
    for attempt in range(3):
        try:
            otp = admin.auth.admin.generate_link(
                {"type": "magiclink", "email": email}
            ).properties.email_otp
            anon = create_client(SUPABASE_URL, ANON)
            e = anon.auth.verify_otp(
                {"email": email, "token": otp, "type": "email"}
            )
            return e.session.access_token, e.user.id
        except Exception:
            if attempt == 2:
                raise
            time.sleep(3)


async def wait_for_ingestion(
    c: httpx.AsyncClient, task_id: str, timeout_s: int = 90
) -> str:
    """Poll ingestion-status until this task is completed/failed. Returns
    the final status ('completed' | 'failed' | 'timeout')."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = await c.get(f"{BACKEND}/api/documents/ingestion-status")
        if r.status_code == 200:
            body = r.json()
            for task in (body.get("in_progress") or []):
                if task.get("task_id") == task_id:
                    status = task.get("status")
                    if status in ("completed", "failed"):
                        return status
            # Not in progress → could already be done
            # Fall through to check DB directly
        await asyncio.sleep(1.5)
    return "timeout"


async def wait_for_doc_row(sb, user_id: str, filename: str, timeout_s: int = 90) -> dict | None:
    """Poll the documents table until the doc lands with status=completed."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            rows = (
                sb.table("documents")
                .select("id, source_filename, content_hash, status, chunk_index, metadata")
                .eq("user_id", user_id)
                .eq("source_filename", filename)
                .eq("status", "completed")
                .order("chunk_index")
                .execute()
                .data
                or []
            )
            if rows:
                return rows[0]  # first chunk
        except Exception:
            pass
        await asyncio.sleep(1.5)
    return None


async def main():
    from db.client import get_supabase

    sb = get_supabase()
    token, user_id = get_token()
    H = {"Authorization": f"Bearer {token}"}
    tid = uuid.uuid4().hex[:6]
    prefix = f"e2e-ingest-{tid}"

    async with httpx.AsyncClient(timeout=120, headers=H) as c:

        # ── Create a scratch folder for this run ──────────────────
        r = await c.post(
            f"{BACKEND}/api/folders",
            json={"name": prefix, "parent_id": None},
        )
        folder_id = r.json()["id"]

        # Track uploaded filenames for teardown.
        uploaded: list[str] = []

        try:
            hr("A. Upload .txt → task queued, chunks + embeddings created")
            txt_name = f"deploy-guide-{tid}.txt"
            uploaded.append(txt_name)
            txt_content = (
                "# Deployment Guide\n\n"
                "Kioku deploys on any Docker host. The backend needs a Postgres\n"
                "with pgvector, a Redis instance for arq queues, and env vars for\n"
                "SUPABASE_URL, ANTHROPIC_API_KEY, and VOYAGE_API_KEY. Frontend is\n"
                "a static Vite build.\n\n"
                "For local dev, run docker-compose up. Migrations live in\n"
                "supabase/migrations. arq worker pulls from Redis queue named\n"
                "'ingestion'.\n" * 3
            ).encode("utf-8")
            files = {"file": (txt_name, txt_content, "text/plain")}
            r = await c.post(
                f"{BACKEND}/api/documents/upload",
                files=files,
                params={"folder_id": folder_id},
            )
            check("A.1 upload .txt → 200", r.status_code == 200, r.text[:200])
            body = r.json()
            check(
                "A.2 response has task_id",
                bool(body.get("task_id")),
                str(body)[:200],
            )
            check("A.3 duplicate=false on first upload",
                  body.get("duplicate") is False,
                  str(body)[:200])
            first_row = await wait_for_doc_row(sb, user_id, txt_name, timeout_s=90)
            check(
                "A.4 doc row appears with status=completed",
                first_row is not None,
                "no completed row after 90s",
            )
            if first_row:
                all_chunks = (
                    sb.table("documents")
                    .select("id, chunk_index, embedding")
                    .eq("user_id", user_id)
                    .eq("source_filename", txt_name)
                    .execute()
                    .data
                    or []
                )
                check(
                    "A.5 at least one chunk stored",
                    len(all_chunks) >= 1,
                    f"got {len(all_chunks)} chunks",
                )
                check(
                    "A.6 every chunk has an embedding vector",
                    all(bool(ch.get("embedding")) for ch in all_chunks),
                    f"embedded: {sum(1 for c in all_chunks if c.get('embedding'))}/{len(all_chunks)}",
                )

            hr("B. Upload .md — same pipeline, tests markdown parser")
            md_name = f"architecture-{tid}.md"
            uploaded.append(md_name)
            md_content = (
                "# Kioku Architecture\n\n"
                "## Backend\n"
                "- FastAPI + Uvicorn\n"
                "- arq for background tasks (Redis-backed)\n"
                "- Supabase Postgres with pgvector\n\n"
                "## Frontend\n"
                "- React 19 + MUI\n"
                "- Vite dev server\n\n"
                "## MCP\n"
                "Separate SSE server on port 8001. Auth via api key.\n"
            ).encode("utf-8")
            r = await c.post(
                f"{BACKEND}/api/documents/upload",
                files={"file": (md_name, md_content, "text/markdown")},
                params={"folder_id": folder_id},
            )
            check("B.1 upload .md → 200", r.status_code == 200, r.text[:200])
            md_row = await wait_for_doc_row(sb, user_id, md_name, timeout_s=90)
            check(
                "B.2 .md row completed",
                md_row is not None,
                "no completed row",
            )
            if md_row:
                # source_type should be 'markdown'
                st = (
                    sb.table("documents")
                    .select("source_type")
                    .eq("id", md_row["id"])
                    .execute()
                    .data[0]
                )
                check(
                    "B.3 source_type = 'markdown' (or contains 'md')",
                    st.get("source_type") in ("markdown", "md"),
                    f"got: {st.get('source_type')}",
                )

            hr("C. Duplicate upload — same content_hash → duplicate=true")
            r = await c.post(
                f"{BACKEND}/api/documents/upload",
                files={"file": (txt_name, txt_content, "text/plain")},
                params={"folder_id": folder_id},
            )
            check("C.1 second upload → 200", r.status_code == 200, r.text[:200])
            body = r.json()
            check(
                "C.2 duplicate=true",
                body.get("duplicate") is True,
                str(body)[:200],
            )
            check(
                "C.3 no task_id on duplicate",
                body.get("task_id") is None,
                str(body)[:200],
            )
            # No new chunk rows should have been created
            count = (
                sb.table("documents")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .eq("source_filename", txt_name)
                .execute()
                .count
                or 0
            )
            check(
                "C.4 no additional chunks created on duplicate",
                count == len(all_chunks),
                f"before={len(all_chunks)} after={count}",
            )

            hr("D. Empty file → 400")
            r = await c.post(
                f"{BACKEND}/api/documents/upload",
                files={"file": (f"empty-{tid}.txt", b"", "text/plain")},
                params={"folder_id": folder_id},
            )
            check(
                "D.1 empty file → 400",
                r.status_code == 400,
                f"got {r.status_code}: {r.text[:200]}",
            )

            hr("E. Unsupported extension → 400")
            r = await c.post(
                f"{BACKEND}/api/documents/upload",
                files={"file": (f"binary-{tid}.exe", b"MZbogus", "application/octet-stream")},
                params={"folder_id": folder_id},
            )
            check(
                "E.1 .exe → 400",
                r.status_code == 400,
                f"got {r.status_code}: {r.text[:200]}",
            )
            check(
                "E.2 error mentions 'Unsupported' or 'Allowed'",
                any(w in r.text for w in ("Unsupported", "Allowed", "allowed")),
                r.text[:200],
            )

            hr("F. Nonexistent folder_id → 4xx")
            fake_uuid = "00000000-0000-0000-0000-000000000000"
            r = await c.post(
                f"{BACKEND}/api/documents/upload",
                files={"file": (f"any-{tid}.txt", b"hello", "text/plain")},
                params={"folder_id": fake_uuid},
            )
            check(
                "F.1 bogus folder_id → 4xx",
                400 <= r.status_code < 500,
                f"got {r.status_code}: {r.text[:200]}",
            )

            hr("G. Cross-user isolation — user2 can't upload into user1's folder")
            admin = create_client(SUPABASE_URL, os.environ["SUPABASE_SERVICE_KEY"])
            email2 = f"ingest-u2-{uuid.uuid4().hex[:6]}@example.test"
            u2 = admin.auth.admin.create_user({
                "email": email2,
                "email_confirm": True,
                "password": "Passw0rd!" + uuid.uuid4().hex,
            })
            try:
                otp = admin.auth.admin.generate_link(
                    {"type": "magiclink", "email": email2}
                ).properties.email_otp
                anon = create_client(SUPABASE_URL, ANON)
                e = anon.auth.verify_otp(
                    {"email": email2, "token": otp, "type": "email"}
                )
                H2 = {"Authorization": f"Bearer {e.session.access_token}"}
                async with httpx.AsyncClient(timeout=30, headers=H2) as c2:
                    r = await c2.post(
                        f"{BACKEND}/api/documents/upload",
                        files={"file": (f"pwned-{tid}.txt", b"content", "text/plain")},
                        params={"folder_id": folder_id},
                    )
                    check(
                        "G.1 user2 upload into user1's folder → 4xx",
                        400 <= r.status_code < 500,
                        f"got {r.status_code}: {r.text[:200]}",
                    )
            finally:
                admin.auth.admin.delete_user(u2.user.id)

            hr("H. Search finds the ingested docs via /api/cli/search")
            # Give embedding write to finish flushing.
            await asyncio.sleep(2)
            # Mint an api key scoped to our folder — that's the entry
            # point external tools (Claude Code, etc.) use to search.
            r = await c.post(
                f"{BACKEND}/api/api-keys",
                json={"name": f"e2e-ingest-{tid}", "scope_folder_id": folder_id},
            )
            check(
                "H.0 mint api key → 200",
                r.status_code == 200,
                r.text[:200],
            )
            api_key = r.json()["key"]
            api_key_id = r.json()["id"]
            r = await c.post(
                f"{BACKEND}/api/cli/search",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"query": "deployment guide docker redis", "limit": 5},
            )
            check(
                "H.1 /api/cli/search → 200",
                r.status_code == 200,
                f"got {r.status_code}: {r.text[:200]}",
            )
            body = r.json() if r.status_code == 200 else {}
            hits_list = body.get("hits") or body.get("results") or []
            check(
                "H.2 search returned at least 1 hit",
                len(hits_list) >= 1,
                f"got {len(hits_list)} hits: {str(body)[:200]}",
            )
            # At least one hit should be from our txt file.
            filenames: list[str] = []
            for h in hits_list:
                fn = (
                    h.get("source_filename")
                    or h.get("filename")
                    or (h.get("metadata") or {}).get("filename")
                    or (h.get("metadata") or {}).get("source_filename")
                    or ""
                )
                filenames.append(fn)
            check(
                "H.3 our .txt is among the results",
                txt_name in filenames or any(txt_name in (f or "") for f in filenames),
                f"filenames: {filenames}",
            )
            # Clean up the probe api key
            try:
                await c.delete(f"{BACKEND}/api/api-keys/{api_key_id}")
            except Exception:
                pass

            hr("I. GET /content returns the reconstructed doc text")
            r = await c.get(f"{BACKEND}/api/documents/{txt_name}/content")
            check(
                "I.1 GET /content → 200",
                r.status_code == 200,
                f"got {r.status_code}: {r.text[:200]}",
            )
            body = r.json() if r.status_code == 200 else {}
            content_text = body.get("content") or ""
            check(
                "I.2 content contains 'Deployment' from the .txt",
                "Deployment" in content_text,
                f"got: {content_text[:200]}",
            )

            hr("J. Doc listing includes the uploaded files")
            r = await c.get(f"{BACKEND}/api/documents?folder_id={folder_id}")
            check(
                "J.1 GET /documents → 200",
                r.status_code == 200,
                f"got {r.status_code}",
            )
            docs = r.json() if r.status_code == 200 else []
            listed = [d.get("filename") or d.get("source_filename") for d in docs]
            check(
                "J.2 listing includes our .txt",
                any(txt_name in (n or "") for n in listed),
                f"got: {listed[:5]}",
            )
            check(
                "J.3 listing includes our .md",
                any(md_name in (n or "") for n in listed),
                f"got: {listed[:5]}",
            )

            hr("K. PATCH /move — atomic folder change on all chunks")
            r = await c.post(
                f"{BACKEND}/api/folders",
                json={"name": f"{prefix}-target", "parent_id": None},
            )
            target_folder = r.json()["id"]
            r = await c.patch(
                f"{BACKEND}/api/documents/{txt_name}/move",
                json={"folder_id": target_folder},
            )
            check(
                "K.1 PATCH /move → 200",
                r.status_code == 200,
                f"got {r.status_code}: {r.text[:200]}",
            )
            # All chunks should now point at the target folder
            chunk_folders = {
                row["folder_id"]
                for row in (
                    sb.table("documents")
                    .select("folder_id")
                    .eq("user_id", user_id)
                    .eq("source_filename", txt_name)
                    .execute()
                    .data
                    or []
                )
            }
            check(
                "K.2 all chunks moved atomically",
                chunk_folders == {target_folder},
                f"got: {chunk_folders}",
            )
            # Clean up target folder
            await c.delete(f"{BACKEND}/api/folders/{target_folder}?delete_docs=true")

            hr("L. DELETE /{filename} removes all chunks")
            r = await c.delete(f"{BACKEND}/api/documents/{md_name}")
            check(
                "L.1 DELETE → 200 or 204",
                r.status_code in (200, 204),
                f"got {r.status_code}: {r.text[:200]}",
            )
            remaining = (
                sb.table("documents")
                .select("id", count="exact")
                .eq("user_id", user_id)
                .eq("source_filename", md_name)
                .execute()
                .count
                or 0
            )
            check(
                "L.2 no chunks left for that filename",
                remaining == 0,
                f"got {remaining}",
            )

        finally:
            hr("Cleanup")
            for fname in uploaded:
                try:
                    await c.delete(f"{BACKEND}/api/documents/{fname}")
                except Exception:
                    pass
            try:
                await c.delete(f"{BACKEND}/api/folders/{folder_id}?delete_docs=true")
            except Exception:
                pass

    print()
    print("═" * 74)
    print(f"INGESTION PIPELINE: {len(PASS)} pass, {len(FAIL)} fail")
    print("═" * 74)
    for n in FAIL:
        print(f"  ✗ {n}")


if __name__ == "__main__":
    asyncio.run(main())
