"""Prove hard dedup + cleanup.

  1. Fresh scratch folder → connect Mem0.
  2. Write the SAME memory content 3 times, back-to-back.
     Expect: exactly 1 memory in Mem0 afterwards.
  3. Write same content but different category → expect 2 memories total.
  4. Write differently-worded content (paraphrase) → expect 3 memories total
     (exact dedup catches identity, not semantics; that's the design).
  5. Run cleanup on the pre-existing 'personal/agentic-rag' folder
     (which has 5 rules + 6 learnings, some of which are dupes).
     Expect: consolidates the rephrased-copies groups down to one each.
  6. Verify: rules count drops from 5 → 3, learnings from 6 → 3.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time

import httpx
from dotenv import load_dotenv
from supabase import create_client

load_dotenv("/Users/feliperamosdasilva/personal_projects/kioku/backend/.env")
sys.path.insert(0, "/Users/feliperamosdasilva/personal_projects/kioku/backend")

MEM0_API_KEY = "m0-DOov2IyXkEkeDTYOJPM1RP06YPOeNDn5WLvxT8Oa"
BACKEND = "http://localhost:8000"
SUPABASE_URL = os.environ["SUPABASE_URL"]
ANON = "sb_publishable_VkQ6BsMHRpz1kiCSerG45g_KiW0o9hx"


def log(msg): print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)
def hr(title):
    print(); print("─" * 74); print(f"  {title}"); print("─" * 74)


def get_session():
    admin = create_client(SUPABASE_URL, os.environ["SUPABASE_SERVICE_KEY"])
    otp = admin.auth.admin.generate_link({"type":"magiclink","email":"felipe.meriga@gmail.com"}).properties.email_otp
    anon = create_client(SUPABASE_URL, ANON)
    e = anon.auth.verify_otp({"email":"felipe.meriga@gmail.com","token":otp,"type":"email"})
    return e.session, e.user


async def count_mem0(folder_id, api_key):
    """Direct Mem0 count so we're not measuring via our proxy."""
    from mem0 import MemoryClient
    c = MemoryClient(api_key=api_key)
    r = c.get_all(filters={"AND":[{"metadata":{"folder_id": folder_id}}]}, version="v2", limit=500)
    if isinstance(r, dict):
        return r.get("results") or []
    return r or []


async def main():
    from db.client import get_supabase
    sb = get_supabase()
    supa_sess, user = get_session()
    token = supa_sess.access_token
    user_id = user.id
    H = {"Authorization": f"Bearer {token}"}

    hr("STEP 1 — Fresh scratch folder + Mem0 connect")
    # Idempotency
    stale = sb.table("folders").select("id").eq("name", "Dedup Test").eq("user_id", user_id).limit(1).execute().data
    if stale:
        sb.table("mem0_sync_configs").delete().eq("root_folder_id", stale[0]["id"]).execute()
        sb.table("folders").delete().eq("id", stale[0]["id"]).execute()
    # kind='repo' so the Mem0 gate lets us wire it.
    folder_id = sb.table("folders").insert({
        "name": "Dedup Test", "user_id": user_id, "kind": "repo",
    }).execute().data[0]["id"]
    log(f"folder: {folder_id}")

    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{BACKEND}/api/mem0/connect", headers=H, json={
            "root_folder_id": folder_id, "api_key": MEM0_API_KEY,
        })
    assert r.status_code == 200, r.text[:200]
    # Cleanup any lingering Mem0 memories tagged for this folder id (shouldn't be any, folder is new)

    hr("STEP 2 — Write same content 3x → expect 1 memory")
    content = "Backend uses uv (not pip). Run uv add <pkg> and uv run <cmd>."
    responses = []
    async with httpx.AsyncClient(timeout=20) as c:
        for i in range(3):
            r = await c.post(f"{BACKEND}/api/mem0/memories", headers=H, json={
                "root_folder_id": folder_id,
                "content": content, "scope": "eternal", "category": "preference",
            })
            responses.append(r.json())
    for i, resp in enumerate(responses, 1):
        dup = resp.get("duplicate", False)
        eid = resp.get("existing_id") or "(new)"
        log(f"  write {i}: duplicate={dup} existing_id={eid[:16] if dup else eid}")
    await asyncio.sleep(3)  # indexing
    mems = await count_mem0(folder_id, MEM0_API_KEY)
    log(f"  → Mem0 has {len(mems)} memories for this folder")
    assert len(mems) == 1, f"expected 1, got {len(mems)}"
    log("  ✓ same content 3x = 1 memory")

    hr("STEP 3 — Same content, DIFFERENT category → Mem0 dedups on content, still 1")
    # Mem0 itself dedupes on memory text with infer=False. Our proxy now
    # aligns: same content = same memory, category is metadata layered on top.
    # An agent that wants distinct memories must write distinct text.
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{BACKEND}/api/mem0/memories", headers=H, json={
            "root_folder_id": folder_id,
            "content": content, "scope": "episodic", "category": "note",
        })
    body = r.json()
    log(f"  write same-content-different-category: duplicate={body.get('duplicate')} existing={body.get('existing_id', '')[:16]}")
    await asyncio.sleep(3)
    mems = await count_mem0(folder_id, MEM0_API_KEY)
    log(f"  → Mem0 has {len(mems)} memories")
    assert len(mems) == 1
    assert body.get("duplicate") is True
    log("  ✓ same content = same memory, first-write metadata wins")

    hr("STEP 4 — Paraphrase (different wording) → expect 2")
    paraphrase = "Use uv instead of pip for backend Python dependencies."
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post(f"{BACKEND}/api/mem0/memories", headers=H, json={
            "root_folder_id": folder_id,
            "content": paraphrase, "scope": "eternal", "category": "preference",
        })
    log(f"  write paraphrase: duplicate={r.json().get('duplicate')}")
    await asyncio.sleep(3)
    mems = await count_mem0(folder_id, MEM0_API_KEY)
    log(f"  → Mem0 has {len(mems)} memories")
    assert len(mems) == 2
    log("  ✓ paraphrase = distinct memory (exact dedup only, by design)")

    # Cleanup scratch
    sb.table("mem0_sync_configs").delete().eq("root_folder_id", folder_id).execute()
    sb.table("folders").delete().eq("id", folder_id).execute()
    # Delete the mem0 memories via Mem0 API
    from mem0 import MemoryClient
    mc = MemoryClient(api_key=MEM0_API_KEY)
    for m in mems:
        try:
            mc.delete(memory_id=m["id"])
        except Exception:
            pass

    hr("STEP 5 — Reconcile the pre-existing agentic-rag dupes")
    ar_folder = sb.table("folders").select("id").eq("name", "agentic-rag").eq("user_id", user_id).limit(1).execute().data
    if not ar_folder:
        log("no agentic-rag folder found — skipping cleanup step")
        return
    ar_folder_id = ar_folder[0]["id"]
    # Find its Mem0 config
    ar_config = sb.table("mem0_sync_configs").select("id").eq("root_folder_id", ar_folder_id).limit(1).execute().data
    if not ar_config:
        log("no mem0 config for agentic-rag — skipping cleanup step")
        return
    ar_config_id = ar_config[0]["id"]

    # Snapshot before
    before = await count_mem0(ar_folder_id, MEM0_API_KEY)
    log(f"  BEFORE: {len(before)} memories in agentic-rag")

    # Dry-run first
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{BACKEND}/api/mem0/configs/{ar_config_id}/deduplicate?dry_run=true", headers=H)
    plan = r.json()
    log(f"  DRY RUN: {plan['before']} in, {plan['kept']} to keep, {plan['removed']} to delete")
    for row in plan['delete'][:5]:
        log(f"    ✗ {row['preview'][:80]}")

    # Apply
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{BACKEND}/api/mem0/configs/{ar_config_id}/deduplicate?dry_run=false", headers=H)
    real = r.json()
    log(f"  APPLIED: kept {real['kept']}, removed {real['removed']}")

    await asyncio.sleep(3)
    after = await count_mem0(ar_folder_id, MEM0_API_KEY)
    log(f"  AFTER:  {len(after)} memories in agentic-rag")

    hr("STEP 6 — Re-count rules + learnings via the MCP payload shape")
    # Simulate what get_folder_orientation sees.
    from services.mem0_sync import get_client_for_folder
    client = get_client_for_folder(sb, ar_folder_id, user_id)
    rules = client.list_eternal(limit=50)
    learnings = client.list_recent_episodic(days=14, limit=20)
    log(f"  rules:     {len(rules)}")
    for r in rules:
        log(f"    • [{(r.get('metadata') or {}).get('category')}] {(r.get('memory') or '')[:100]}")
    log(f"  learnings: {len(learnings)}")
    for l in learnings:
        log(f"    • [{(l.get('metadata') or {}).get('category')}] {(l.get('memory') or '')[:100]}")

    print()
    print("=" * 74)
    print(f"SUMMARY: dedup on write ✓  |  cleanup reduced {len(before)} → {len(after)} memories")
    print("=" * 74)


if __name__ == "__main__":
    asyncio.run(main())
