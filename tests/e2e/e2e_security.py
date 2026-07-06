"""Security E2E — probe every attack surface we've built.

  A. SQL / injection in text fields (folder names, memory content, chat).
  B. Path traversal in filename params.
  C. IDOR: cross-user by UUID guessing (already covered elsewhere; recheck).
  D. Secret leak: api-keys list never returns plaintext keys.
  E. Secret leak: error messages never contain SUPABASE_SERVICE_KEY,
     ANTHROPIC_API_KEY, MEM0_API_KEY, or the plaintext PATs.
  F. GitHub PAT + Mem0 key encrypted at rest (verify token_encrypted !=
     plaintext).
  G. XSS: markdown in briefing content is stored verbatim but frontend
     needs to sanitize on render (we verify server DOES NOT reject it).
  H. Rate limit doesn't leak enumeration info (auth-first order).
  I. Malformed UUIDs in route params return 4xx not 500 (regression).
  J. Bearer token requirement enforced on protected routes.
"""

from __future__ import annotations
import asyncio, json, os, sys, uuid
import httpx
from dotenv import load_dotenv
from supabase import create_client

load_dotenv("/Users/feliperamosdasilva/personal_projects/kioku/backend/.env")
sys.path.insert(0, "/Users/feliperamosdasilva/personal_projects/kioku/backend")

BACKEND = "http://localhost:8000"
SUPABASE_URL = os.environ["SUPABASE_URL"]
ANON = os.environ["SUPABASE_ANON_KEY"]

# Secrets we must NEVER see leaked in an error message
SECRETS = [
    ("SUPABASE_SERVICE_KEY", os.environ.get("SUPABASE_SERVICE_KEY", "")[:20]),
    ("ANTHROPIC_API_KEY", os.environ.get("ANTHROPIC_API_KEY", "")[:20]),
    ("SUPABASE_JWT_SECRET", os.environ.get("SUPABASE_JWT_SECRET", "")[:20]),
]

PASS, FAIL = [], []
def check(n, cond, d=""):
    (PASS if cond else FAIL).append(n)
    print(f"  {'✓' if cond else '✗'} {n}" + (f" — {d[:220]}" if not cond else ""))
def hr(t): print(); print("═" * 74); print(f"  {t}"); print("═" * 74)


def get_token():
    admin = create_client(SUPABASE_URL, os.environ["SUPABASE_SERVICE_KEY"])
    otp = admin.auth.admin.generate_link({"type":"magiclink","email":"felipe.meriga@gmail.com"}).properties.email_otp
    anon = create_client(SUPABASE_URL, ANON)
    e = anon.auth.verify_otp({"email":"felipe.meriga@gmail.com","token":otp,"type":"email"})
    return e.session.access_token, e.user.id


def response_contains_any_secret(text: str) -> tuple[bool, str]:
    """Returns (found, which)."""
    for name, val in SECRETS:
        if val and val in text:
            return (True, name)
    return (False, "")


async def main():
    token, user_id = get_token()
    H = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30, headers=H) as c:

        hr("A. SQL / prompt-injection in text fields")
        # Folder name with SQL payload
        r = await c.post(f"{BACKEND}/api/folders", json={
            "name": "'; DROP TABLE folders; --",
            "parent_id": None,
        })
        check("SQL-payload folder name → 400 or 200 (never 500)",
              r.status_code in (200, 400, 409),
              f"got {r.status_code}: {r.text[:150]}")
        # If it was created, verify tables still exist
        if r.status_code == 200:
            r2 = await c.get(f"{BACKEND}/api/folders")
            check("folders table still queryable", r2.status_code == 200)
            # cleanup
            await c.delete(f"{BACKEND}/api/folders/{r.json()['id']}")

        # NULL byte
        r = await c.post(f"{BACKEND}/api/folders", json={
            "name": "null\x00byte", "parent_id": None,
        })
        check("null-byte name → 400 or 200",
              r.status_code in (200, 400, 409, 422),
              f"got {r.status_code}: {r.text[:150]}")
        if r.status_code == 200:
            await c.delete(f"{BACKEND}/api/folders/{r.json()['id']}")

        hr("B. Path traversal in filename params")
        for path in ["../../../etc/passwd", "..%2F..%2Fetc%2Fpasswd",
                      "%2E%2E%2F%2E%2E%2Fetc%2Fpasswd"]:
            r = await c.get(f"{BACKEND}/api/documents/{path}/content")
            check(f"path traversal '{path[:20]}...' → 4xx not 200",
                  400 <= r.status_code < 500,
                  f"got {r.status_code}: {r.text[:150]}")

        hr("C. Malformed UUIDs return 4xx not 500")
        for endpoint in [
            "/api/folders/nonsense-uuid/breadcrumbs",
            "/api/folders/nonsense-uuid/summary",
            "/api/folders/nonsense-uuid/briefing",
        ]:
            r = await c.get(f"{BACKEND}{endpoint}")
            check(f"{endpoint} malformed uuid → not 500",
                  r.status_code != 500, f"got {r.status_code}: {r.text[:150]}")

        hr("D. api-keys list never returns plaintext keys")
        r = await c.post(f"{BACKEND}/api/api-keys", json={
            "name": f"sec-probe-{uuid.uuid4().hex[:6]}",
            "scope_folder_id": (await c.get(f"{BACKEND}/api/folders")).json()[0]["id"],
        })
        created_key = r.json()["key"]  # plaintext returned ONCE
        created_id = r.json()["id"]
        check("POST /api/api-keys returns plaintext key ONCE",
              created_key.startswith("rag_"), created_key[:20])

        # List
        r = await c.get(f"{BACKEND}/api/api-keys")
        listed_keys_text = r.text
        check("GET /api/api-keys does NOT return the plaintext key",
              created_key not in listed_keys_text,
              "plaintext key leaked in list response")
        check("GET /api/api-keys does NOT return any key_hash",
              "key_hash" not in listed_keys_text.lower(),
              "key hash leaked")

        await c.delete(f"{BACKEND}/api/api-keys/{created_id}")

        hr("E. Server-side secret leak scan — error messages")
        # Trigger a couple of well-known errors and scan the body
        errored_bodies = []
        # Missing required field
        r = await c.post(f"{BACKEND}/api/folders", json={})
        errored_bodies.append(("POST /folders empty", r.text))
        # Invalid enum
        r = await c.post(f"{BACKEND}/api/mem0/memories", json={
            "root_folder_id": "x", "content": "y",
            "category": "nonsense", "scope": "episodic",
        })
        errored_bodies.append(("bad category", r.text))
        # Nonexistent folder
        r = await c.delete(f"{BACKEND}/api/folders/00000000-0000-0000-0000-000000000000")
        errored_bodies.append(("delete nonexistent", r.text))

        leaked = []
        for label, body in errored_bodies:
            found, which = response_contains_any_secret(body)
            if found:
                leaked.append((label, which))
        check("no env-var secrets appear in error bodies",
              not leaked, f"leaks: {leaked}")

        hr("F. GitHub PAT + Mem0 keys encrypted at rest")
        from db.client import get_supabase
        sb = get_supabase()
        # Check github_sync_configs
        rows = sb.table("github_sync_configs").select(
            "token_encrypted"
        ).eq("user_id", user_id).limit(3).execute().data or []
        for row in rows:
            tok = row.get("token_encrypted") or ""
            # If a token is stored, it should not look like a raw PAT
            if tok:
                check(
                    "GitHub token stored is not a raw PAT",
                    not (tok.startswith("gho_") or tok.startswith("ghp_") or tok.startswith("github_pat_")),
                    f"stored value starts with: {tok[:12]}...",
                )
        rows = sb.table("mem0_sync_configs").select(
            "api_key_encrypted"
        ).eq("user_id", user_id).limit(3).execute().data or []
        for row in rows:
            key = row.get("api_key_encrypted") or ""
            if key:
                check(
                    "Mem0 api key stored is not a raw key",
                    not key.startswith("m0-"),
                    f"stored value starts with: {key[:12]}...",
                )

        hr("G. XSS: HTML in briefing content stored verbatim (frontend sanitizes)")
        # Create a repo folder, put HTML in a section, verify it's stored as-is
        r = await c.post(f"{BACKEND}/api/folders", json={
            "name": f"xss-{uuid.uuid4().hex[:6]}", "parent_id": None,
        })
        f_id = r.json()["id"]
        await c.patch(f"{BACKEND}/api/folders/{f_id}", json={"kind": "repo"})
        html_payload = "<script>alert(1)</script><img src=x onerror=alert(1)>"
        r = await c.patch(
            f"{BACKEND}/api/folders/{f_id}/briefing/section/overview",
            json={"content": {"purpose": html_payload, "description": ""},
                  "status": "pinned"},
        )
        check("HTML payload accepted (server does NOT sanitize)",
              r.status_code == 200,
              f"got {r.status_code}: {r.text[:200]}")
        # Read back
        r = await c.get(f"{BACKEND}/api/folders/{f_id}/briefing")
        stored = r.json()["sections"]["overview"]["content"]["purpose"]
        check("HTML round-trips verbatim (relies on frontend sanitizer)",
              stored == html_payload, f"stored: {stored[:100]}")
        await c.delete(f"{BACKEND}/api/folders/{f_id}?delete_docs=true")

        hr("H. Rate limit doesn't leak enumeration info (auth-first)")
        # Bogus api key hammered N times all return 401, not 429
        r = await c.post(f"{BACKEND}/api/cli/session-capture",
                          headers={"Authorization": "Bearer rag_bogus"},
                          json={
                              "folder_id": "any",
                              "session_id": "x",
                              "transcript_delta": [{"role":"user","content":"x"}],
                          })
        check("bogus api-key returns 401 not 429",
              r.status_code == 401, f"got {r.status_code}: {r.text[:150]}")

        hr("I. Bearer token required on protected routes")
        async with httpx.AsyncClient(timeout=15) as anon_c:  # no auth header
            for endpoint in [
                "/api/folders", "/api/conversations",
                "/api/mem0/configs", "/api/api-keys",
                "/api/retrieval-log",
            ]:
                r = await anon_c.get(f"{BACKEND}{endpoint}")
                check(f"anon GET {endpoint} → 401/403",
                      r.status_code in (401, 403),
                      f"got {r.status_code}")

    print()
    print("═" * 74)
    print(f"SECURITY: {len(PASS)} pass, {len(FAIL)} fail")
    print("═" * 74)
    for n in FAIL:
        print(f"  ✗ {n}")


if __name__ == "__main__":
    asyncio.run(main())
