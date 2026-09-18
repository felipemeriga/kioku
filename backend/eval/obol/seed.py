"""Seed (and tear down) the Obol golden dataset through the REAL pipeline.

Builds a faithful company scope for retrieval + cross-repo relationship tests:

    Obol/                         (root folder = the company)
    ├── [12 long docs ingested as documents at the root]
    └── repositories/
        ├── obol-gateway   (Go)      -> code_chunks
        ├── obol-ledger    (Python)  -> code_chunks
        └── obol-console   (TypeScript) -> code_chunks

Docs are uploaded to Storage and ingested via the same ingest_document_task
the web upload uses. Repos are chunked (120-line windows, symbol-aware where
cheap) and embedded with voyage-code-3, exactly like the CLI's code-chunk
upload, then inserted into code_chunks under each repo's folder — so semantic
code_search and the doc pipeline both see Obol as a real scope.

Run inside the backend environment / container:
    python -m eval.obol.seed <user_id>            # build tree + ingest + index
    python -m eval.obol.seed <user_id> --teardown # remove everything

Idempotent: re-seeding clears prior Obol docs + code_chunks first.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from arq import create_pool

from db.client import get_supabase
from services.embeddings import embed_batch, embed_code_batch
from services.ingestion import compute_content_hash, upload_document_to_storage
from services.queue.jobs import create_job
from services.queue.settings import _redis_settings

ROOT_NAME = "Obol"
REPOS_NAME = "repositories"
REPO_DIRS = ["obol-gateway", "obol-ledger", "obol-console"]

BASE = Path(__file__).parent
DOCS_DIR = BASE / "docs"
REPOS_DIR = BASE / "repos"

# Prefix for the synthetic DATED corpus so the temporal eval can isolate its
# own rows from the static docs/code.
DATED_PREFIX = "obol-dated-"

# Backdated meeting/decision notes for temporal scenarios (recency decay, date
# filters). Inserted directly with real embeddings + a chosen created_at and
# source_type — meetings decay (half-life 90d), reference text does not. Written
# in Obol's domain so the whole company exercises time too.
# Topics are deliberately MEETING-ONLY (incidents, migrations, team policy) —
# absent from the 12 product docs — so a query about them cleanly retrieves the
# dated rows instead of being swamped by the rich static corpus.
#   (name, age_days, source_type, content)
DATED = [
    (
        "inc204-decision",
        400,
        "meeting",
        "Incident INC-204 review — the Lisbon region checkout outage. Decision: "
        "add a regional failover for the checkout path and run a synthetic canary "
        "every 60 seconds against each region. Owner: platform team. This is the "
        "agreed remediation for the INC-204 Lisbon outage.",
    ),
    (
        "inc204-mention",
        2,
        "meeting",
        "Standup: quick mention that the INC-204 follow-ups are on track; nothing "
        "new. Most of the time went to the offsite agenda and hiring.",
    ),
    (
        "lighthouse-strong-old",
        365,
        "meeting",
        "Project Lighthouse migration decision: move the ledger store to the new "
        "partitioned schema over three weekend windows, dual-writing during "
        "cutover and backfilling historical journal entries in batches. This is "
        "the agreed Lighthouse ledger migration plan.",
    ),
    (
        "lighthouse-weak-old",
        350,
        "meeting",
        "Standup notes: Project Lighthouse was briefly noted as on track this "
        "sprint; no decisions taken.",
    ),
    (
        "prpolicy-twin-old",
        200,
        "meeting",
        "Sprint 47 retro: agreed to cap pull requests at 400 changed lines and "
        "require two reviewers for any change to the ledger service.",
    ),
    (
        "prpolicy-twin-fresh",
        2,
        "meeting",
        "Sprint 61 retro: reaffirmed capping pull requests at 400 changed lines "
        "and requiring two reviewers for any change to the ledger service.",
    ),
    (
        "escalation-ref",
        380,
        "text",
        "Reference — incident escalation matrix: a Sev1 pages the CTO within 10 "
        "minutes; a Sev2 pages the on-call lead within 30 minutes; Sev3 is "
        "handled next business day. Stable reference material.",
    ),
]

# Extension -> language, mirroring the CLI's EXT_LANGUAGE. Files whose
# extension isn't here are NOT indexed as code (matches production hygiene).
EXT_LANGUAGE = {
    "py": "python",
    "ts": "typescript",
    "tsx": "typescript",
    "js": "javascript",
    "jsx": "javascript",
    "go": "go",
    "rs": "rust",
    "java": "java",
    "sql": "sql",
    "sh": "bash",
    "proto": "proto",
}

MAX_CHUNK_LINES = 120
OVERLAP_LINES = 10
MAX_CHUNK_CHARS = 8000
MAX_FILE_BYTES = 300_000
SKIP_DIRS = {"node_modules", ".git", "dist", "build", "vendor", "__pycache__", ".venv"}

# Cheap symbol detection — nearest preceding definition in a chunk window.
SYMBOL_PATTERNS = [
    re.compile(r"^\s*(?:public|private|protected)?\s*(?:async\s+)?def\s+(\w+)"),
    re.compile(r"^\s*class\s+(\w+)"),
    re.compile(r"^func\s+(?:\([^)]*\)\s*)?(\w+)"),
    re.compile(r"^type\s+(\w+)\s"),
    re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)"),
    re.compile(r"^\s*(?:export\s+)?(?:abstract\s+)?class\s+(\w+)"),
    re.compile(r"^\s*(?:export\s+)?const\s+(\w+)\s*="),
    re.compile(r"^\s*(?:export\s+)?interface\s+(\w+)"),
]


# ── folder tree ────────────────────────────────────────────────────


def _get_or_create_folder(sb, user_id: str, name: str, parent_id: str | None) -> str:
    q = sb.table("folders").select("id").eq("user_id", user_id).eq("name", name)
    q = q.is_("parent_id", "null") if parent_id is None else q.eq("parent_id", parent_id)
    rows = q.execute().data or []
    if rows:
        return rows[0]["id"]
    kind = "repo" if name in REPO_DIRS else "folder"
    created = (
        sb.table("folders")
        .insert({"user_id": user_id, "name": name, "kind": kind, "parent_id": parent_id})
        .execute()
    ).data
    return created[0]["id"]


def _build_tree(sb, user_id: str) -> tuple[str, dict[str, str]]:
    root = _get_or_create_folder(sb, user_id, ROOT_NAME, None)
    repos = _get_or_create_folder(sb, user_id, REPOS_NAME, root)
    repo_ids = {name: _get_or_create_folder(sb, user_id, name, repos) for name in REPO_DIRS}
    return root, repo_ids


# ── docs (real ingestion) ──────────────────────────────────────────


async def _ingest_docs(sb, user_id: str, root_id: str) -> list[str]:
    files = sorted(f for f in DOCS_DIR.glob("*.md") if not f.name.startswith("._"))
    if not files:
        raise SystemExit(f"no docs under {DOCS_DIR}")
    pool = await create_pool(_redis_settings())
    job_ids: list[str] = []
    try:
        for f in files:
            file_bytes = f.read_bytes()
            content_hash = compute_content_hash(file_bytes)
            storage_path = upload_document_to_storage(file_bytes, user_id, content_hash, f.name)
            job_id = create_job(
                sb, user_id=user_id, kind="upload", source_ref=f.name, root_folder_id=root_id
            )
            await pool.enqueue_job(
                "ingest_document_task",
                {
                    "job_id": job_id,
                    "user_id": user_id,
                    "folder_id": root_id,
                    "root_folder_id": root_id,
                    "storage_bucket": "documents",
                    "storage_path": storage_path,
                    "filename": f.name,
                    "source_type": "text",
                    "media_kind": "document",
                    "media_url": storage_path,
                    "content_hash": content_hash,
                },
            )
            job_ids.append(job_id)
            print(f"  enqueued doc {f.name} (job {job_id[:8]})")
    finally:
        await pool.close()
    return job_ids


def _seed_dated(sb, user_id: str, root_id: str) -> int:
    """Insert the backdated meeting/decision corpus directly (real doc
    embeddings, chosen created_at + source_type) so temporal scenarios have
    controlled ages. Bypasses the queue because the ingest task always stamps
    created_at = now."""
    now = datetime.now(timezone.utc)
    embeddings = embed_batch([content for _, _, _, content in DATED])
    rows = []
    for (name, age_days, source_type, content), emb in zip(DATED, embeddings, strict=True):
        src = f"{DATED_PREFIX}{name}"
        rows.append(
            {
                "user_id": user_id,
                # folder_id is what match_documents/keyword_search filter on for
                # scope; root_folder_id alone would exclude these from a
                # folder-scoped search. Both point at the Obol root.
                "folder_id": root_id,
                "root_folder_id": root_id,
                "source_filename": src,
                "source_type": source_type,
                "content": content,
                "embedding": emb,
                "status": "completed",
                "content_hash": uuid.uuid4().hex,
                "created_at": (now - timedelta(days=age_days)).isoformat(),
                "metadata": {"source_filename": src, "chunk_index": 0},
            }
        )
    for i in range(0, len(rows), 10):
        sb.table("documents").insert(rows[i : i + 10]).execute()
    print(f"  dated: {len(rows)} backdated docs")
    return len(rows)


def _wait_for_ingestion(sb, job_ids: list[str], timeout_s: int = 600) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        rows = (
            sb.table("ingestion_jobs").select("id,status").in_("id", job_ids).execute()
        ).data or []
        by_status: dict[str, int] = {}
        for r in rows:
            by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        done = by_status.get("completed", 0) + by_status.get("failed", 0)
        print(f"  ingestion: {by_status}")
        if done >= len(job_ids):
            return by_status.get("failed", 0) == 0
        time.sleep(5)
    return False


# ── code indexing (faithful to the CLI's code-chunk upload) ─────────


def _symbol_for(lines: list[str]) -> str | None:
    for line in lines:
        for pat in SYMBOL_PATTERNS:
            m = pat.match(line)
            if m:
                return m.group(1)
    return None


def _chunk_file(repo_name: str, rel_path: str, content: str) -> list[dict]:
    lines = content.split("\n")
    n = len(lines)
    out: list[dict] = []
    a = 1
    step = MAX_CHUNK_LINES - OVERLAP_LINES
    while a <= n:
        b = min(a + MAX_CHUNK_LINES - 1, n)
        window = lines[a - 1 : b]
        body = "\n".join(window)
        if body.strip():
            symbol = _symbol_for(window)
            header = f"[repo {repo_name}] [file {rel_path}:{a}-{b}]" + (
                f" [symbol {symbol}]" if symbol else ""
            )
            text = f"{header}\n{body}"
            out.append(
                {
                    "file": rel_path,
                    "symbol": symbol,
                    "start_line": a,
                    "end_line": b,
                    "language": EXT_LANGUAGE.get(rel_path.rsplit(".", 1)[-1]),
                    "content": text[:MAX_CHUNK_CHARS],
                }
            )
        if b >= n:
            break
        a += step
    return out


def _iter_source_files(repo_root: Path):
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(repo_root).parts):
            continue
        ext = path.suffix.lstrip(".").lower()
        if ext not in EXT_LANGUAGE:
            continue
        if path.stat().st_size > MAX_FILE_BYTES:
            continue
        yield path


def _index_repo(sb, user_id: str, repo_name: str, folder_id: str) -> int:
    repo_root = REPOS_DIR / repo_name
    if not repo_root.is_dir():
        raise SystemExit(f"missing repo dir {repo_root}")
    rows: list[dict] = []
    for path in _iter_source_files(repo_root):
        rel = str(path.relative_to(repo_root))
        content = path.read_text(errors="replace")
        if "\x00" in content:  # binary guard, mirrors the CLI NUL check
            continue
        file_hash = hashlib.sha256(content.encode()).hexdigest()
        for ch in _chunk_file(repo_name, rel, content):
            rows.append(
                {
                    "user_id": user_id,
                    "folder_id": folder_id,
                    "file": ch["file"],
                    "language": ch["language"],
                    "symbol": ch["symbol"],
                    "start_line": ch["start_line"],
                    "end_line": ch["end_line"],
                    "content": ch["content"],
                    "file_hash": file_hash,
                    "embedding_model": "voyage-code-3",
                }
            )
    if not rows:
        print(f"  {repo_name}: no source chunks")
        return 0
    # Embed (128/API call) then insert in small sub-batches. 1024-dim vectors
    # make the JSON payload heavy, so keep batches tiny and retry on the
    # PostgREST read-timeout that larger batches trigger.
    embeddings = embed_code_batch([r["content"] for r in rows])
    for r, emb in zip(rows, embeddings, strict=True):
        r["embedding"] = emb
    for i in range(0, len(rows), 10):
        batch = rows[i : i + 10]
        for attempt in range(4):
            try:
                sb.table("code_chunks").insert(batch).execute()
                break
            except Exception as exc:  # noqa: BLE001 — retry heavy inserts
                if attempt == 3:
                    raise
                print(f"    insert retry {attempt + 1} ({type(exc).__name__})")
                time.sleep(2 * (attempt + 1))
    print(f"  {repo_name}: {len(rows)} code chunks")
    return len(rows)


# ── orchestration ──────────────────────────────────────────────────


def _clear(sb, user_id: str, root_id: str, repo_ids: dict[str, str]) -> None:
    doc_ids = [
        r["id"]
        for r in (
            sb.table("documents").select("id").eq("root_folder_id", root_id).execute().data or []
        )
    ]
    if doc_ids:
        sb.table("documents").delete().in_("id", doc_ids).execute()
        print(f"  cleared {len(doc_ids)} prior docs")
    for name, fid in repo_ids.items():
        sb.table("code_chunks").delete().eq("folder_id", fid).execute()


def _index_all(sb, user_id: str, repo_ids: dict[str, str]) -> int:
    total = 0
    for name, fid in repo_ids.items():
        sb.table("code_chunks").delete().eq("folder_id", fid).execute()
        total += _index_repo(sb, user_id, name, fid)
    return total


def seed(user_id: str, code_only: bool = False) -> int:
    sb = get_supabase()
    root, repo_ids = _build_tree(sb, user_id)
    print(f"tree: {ROOT_NAME}={root}  repos={ {k: v[:8] for k, v in repo_ids.items()} }")

    if code_only:
        # Leave already-ingested docs in place; re-index code only.
        total_chunks = _index_all(sb, user_id, repo_ids)
        doc_chunks = (
            sb.table("documents").select("id", count="exact").eq("root_folder_id", root).execute()
        ).count
        print(f"\nCODE-ONLY OK: {doc_chunks} doc chunks (kept), {total_chunks} code chunks")
        return 0 if total_chunks else 1

    _clear(sb, user_id, root, repo_ids)

    job_ids = asyncio.run(_ingest_docs(sb, user_id, root))
    print(f"ingesting {len(job_ids)} docs...")
    docs_ok = _wait_for_ingestion(sb, job_ids)

    _seed_dated(sb, user_id, root)

    total_chunks = _index_all(sb, user_id, repo_ids)

    doc_chunks = (
        sb.table("documents").select("id", count="exact").eq("root_folder_id", root).execute()
    ).count
    print(
        f"\n{'OK' if docs_ok else 'DOCS INCOMPLETE'}: "
        f"{doc_chunks} doc chunks, {total_chunks} code chunks under {ROOT_NAME}"
    )
    return 0 if docs_ok and total_chunks else 1


def teardown(user_id: str) -> int:
    sb = get_supabase()
    root = _get_or_create_folder(sb, user_id, ROOT_NAME, None)
    repos = _get_or_create_folder(sb, user_id, REPOS_NAME, root)
    repo_ids = {n: _get_or_create_folder(sb, user_id, n, repos) for n in REPO_DIRS}
    _clear(sb, user_id, root, repo_ids)
    for fid in repo_ids.values():
        sb.table("folders").delete().eq("id", fid).execute()
    sb.table("folders").delete().eq("id", repos).execute()
    sb.table("folders").delete().eq("id", root).execute()
    print(f"removed {ROOT_NAME} tree")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m eval.obol.seed <user_id> [--teardown|--code-only]")
        sys.exit(2)
    uid = sys.argv[1]
    if "--teardown" in sys.argv:
        sys.exit(teardown(uid))
    sys.exit(seed(uid, code_only="--code-only" in sys.argv))
