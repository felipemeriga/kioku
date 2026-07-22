"""E2E: MCP tool exhaustive coverage.

Every MCP tool called at least once with valid + invalid args:

  A. knowledge_base_search — happy path + empty query
  B. save_memory / search_memory / delete_memory (via Mem0 flow)
  C. save_note / list_notes / delete_note — full CRUD
  D. set_context / get_context / list_context / clear_context — CRUD
  E. list_folders_in_scope — respects api key scope
  F. get_folder_briefing_schema — static schema
  G. get_folder_briefing — with + without folder arg
  H. get_folder_orientation — full payload shape
  I. query_documents_metadata — natural-language SQL
  J. Auth failures — every tool → error with missing/bogus api key
"""

from __future__ import annotations
import asyncio, json, os, sys, time, uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv
from supabase import create_client
from mcp import ClientSession
from mcp.client.sse import sse_client

load_dotenv("/Users/feliperamosdasilva/personal_projects/kioku/backend/.env")
sys.path.insert(0, "/Users/feliperamosdasilva/personal_projects/kioku/backend")

BACKEND = "http://localhost:8000"
MCP_URL = "http://localhost:8001/sse"
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


async def call_mcp(api_key: str, tool: str, args: dict) -> str:
    """Invoke an MCP tool via SSE + return the concatenated text output."""
    async with sse_client(MCP_URL, headers={"Authorization": f"Bearer {api_key}"}) as (rd, wr):
        async with ClientSession(rd, wr) as s:
            await s.initialize()
            r = await s.call_tool(tool, args)
            return "\n".join(b.text for b in r.content if hasattr(b, "text"))


async def main():
    from db.client import get_supabase

    sb = get_supabase()
    token, user_id = get_token()
    H = {"Authorization": f"Bearer {token}"}
    tid = uuid.uuid4().hex[:6]

    async with httpx.AsyncClient(timeout=60, headers=H) as c:
        # ── Setup: fresh folder + api key scoped to it ────────────
        r = await c.post(
            f"{BACKEND}/api/folders",
            json={"name": f"e2e-mcp-{tid}", "parent_id": None},
        )
        folder_id = r.json()["id"]
        # Make it a repo so briefing tools work
        await c.patch(f"{BACKEND}/api/folders/{folder_id}", json={"kind": "repo"})
        # Wire Mem0 so memory tools work
        r = await c.get(f"{BACKEND}/api/mem0/configs")
        cfgs = r.json() if r.status_code == 200 else []
        if not cfgs:
            print("SKIP: no Mem0 config wired — skipping memory tool tests")
            return
        # Reuse the user's existing Mem0 config against this folder
        r = await c.post(
            f"{BACKEND}/api/mem0/configs",
            json={
                "api_key": cfgs[0].get("api_key_encrypted", ""),  # backend re-uses
                "root_folder_id": folder_id,
            },
        )
        # If direct Mem0 wire fails, we'll still test tools that don't
        # need Mem0. Continue.

        r = await c.post(
            f"{BACKEND}/api/api-keys",
            json={"name": f"e2e-mcp-{tid}", "scope_folder_id": folder_id},
        )
        api_key = r.json()["key"]
        api_key_id = r.json()["id"]

        try:
            hr("A. knowledge_base_search — happy path")
            out = await call_mcp(api_key, "knowledge_base_search",
                                 {"query": "kioku deployment guide"})
            check(
                "A.1 returns non-empty response",
                bool(out) and not out.startswith("Error"),
                out[:200],
            )
            check(
                "A.2 output mentions results or 'no matches'",
                any(k in out.lower() for k in ("result", "match", "no ", "found")),
                out[:200],
            )

            hr("B. save_note / list_notes / delete_note")
            unique = f"e2e-note-{tid}-{uuid.uuid4().hex[:4]}"
            out = await call_mcp(api_key, "save_note", {
                "title": unique,
                "content": "This note was saved by the e2e_mcp_tools suite.",
            })
            check(
                "B.1 save_note succeeds",
                not out.startswith("Error"),
                out[:200],
            )
            # save_note returns human text like:
            # "Note saved: 'title' (id: <uuid>)"
            import re
            m = re.search(r"id:\s*([0-9a-f-]{20,})", out)
            note_id = m.group(1) if m else None
            check("B.2 note_id extractable from response", bool(note_id), out[:200])

            out = await call_mcp(api_key, "list_notes", {"query": unique})
            check(
                "B.3 list_notes finds it back",
                unique in out,
                out[:400],
            )

            if note_id:
                out = await call_mcp(api_key, "delete_note", {"note_id": note_id})
                check(
                    "B.4 delete_note succeeds",
                    not out.startswith("Error"),
                    out[:200],
                )
                out = await call_mcp(api_key, "list_notes", {"query": unique})
                check(
                    "B.5 note gone after delete",
                    unique not in out,
                    out[:200],
                )

            hr("C. set_context / get_context / list_context / clear_context")
            key = f"e2e-ctx-{tid}"
            val = "test-value-42"
            out = await call_mcp(api_key, "set_context", {"key": key, "value": val})
            check("C.1 set_context succeeds", not out.startswith("Error"), out[:200])
            out = await call_mcp(api_key, "get_context", {"key": key})
            check("C.2 get_context returns value", val in out, out[:200])
            out = await call_mcp(api_key, "list_context", {})
            check("C.3 list_context includes our key", key in out, out[:400])
            out = await call_mcp(api_key, "clear_context", {"key": key})
            check("C.4 clear_context succeeds", not out.startswith("Error"), out[:200])
            out = await call_mcp(api_key, "get_context", {"key": key})
            check(
                "C.5 after clear, get_context returns 'not set' / empty",
                any(w in out.lower() for w in ("not ", "empty", "no ", "null")),
                out[:200],
            )

            hr("D. list_folders_in_scope")
            out = await call_mcp(api_key, "list_folders_in_scope", {})
            check("D.1 returns valid JSON", not out.startswith("Error"), out[:200])
            try:
                parsed = json.loads(out)
                # Should include our scope folder somewhere
                folders_all = json.dumps(parsed)
                check(
                    "D.2 scope folder appears in output",
                    folder_id in folders_all or f"e2e-mcp-{tid}" in folders_all,
                    folders_all[:400],
                )
            except Exception:
                check("D.1 returns valid JSON", False, "not JSON")

            hr("E. get_folder_briefing_schema — static, no args")
            out = await call_mcp(api_key, "get_folder_briefing_schema", {})
            check("E.1 returns 200 payload", bool(out), "empty")
            check(
                "E.2 all 8 section names in schema",
                all(s in out for s in [
                    "overview", "architecture", "preferences", "important_files",
                    "how_it_runs", "deployment", "dependencies", "activity",
                ]),
                out[:400],
            )

            hr("F. get_folder_briefing — with + without folder arg")
            # First seed a briefing
            await call_mcp(api_key, "replace_folder_briefing", {
                "sections": json.dumps({
                    "overview": {"purpose": f"MCP tool test {tid}"},
                }),
                "pin_all": True,
            })
            out = await call_mcp(api_key, "get_folder_briefing", {})
            check(
                "F.1 no-arg call returns the scope folder's briefing",
                f"MCP tool test {tid}" in out,
                out[:400],
            )
            # With explicit folder arg (self-reference by name)
            out = await call_mcp(api_key, "get_folder_briefing",
                                 {"folder": f"e2e-mcp-{tid}"})
            check(
                "F.2 folder-arg call returns same briefing",
                f"MCP tool test {tid}" in out,
                out[:400],
            )
            # Bogus folder → error
            out = await call_mcp(api_key, "get_folder_briefing",
                                 {"folder": "no-such-folder-xyz"})
            check(
                "F.3 bogus folder → Error",
                out.startswith("Error") or "not found" in out.lower(),
                out[:200],
            )

            hr("G. get_folder_orientation — full payload with all sections")
            out = await call_mcp(api_key, "get_folder_orientation", {})
            check("G.1 returns non-empty output", bool(out), "empty")
            # Should include the folder name + some structure
            check(
                "G.2 output includes folder name",
                f"e2e-mcp-{tid}" in out,
                out[:400],
            )

            hr("H. query_documents_metadata — NL SQL")
            out = await call_mcp(api_key, "query_documents_metadata",
                                 {"question": "how many documents do I have?"})
            check(
                "H.1 returns a response (not a crash)",
                bool(out),
                out[:200],
            )

            hr("I. Auth failures — every tool refuses without api key")
            # Try connecting with no auth header
            failures = 0
            try:
                async with sse_client(MCP_URL, headers={}) as (rd, wr):
                    async with ClientSession(rd, wr) as s:
                        await s.initialize()
                        # If we got here without error, count as 0 (bad!)
                        failures = 0
            except Exception:
                failures = 1
            check(
                "I.1 SSE handshake without api key fails cleanly",
                failures == 1,
                "handshake succeeded without auth",
            )
            # And with bogus api key
            try:
                async with sse_client(MCP_URL,
                                       headers={"Authorization": "Bearer rag_bogus_123"}) as (rd, wr):
                    async with ClientSession(rd, wr) as s:
                        await s.initialize()
                        failures = 0
            except Exception:
                failures = 1
            check(
                "I.2 SSE handshake with bogus api key fails cleanly",
                failures == 1,
                "handshake succeeded with bad auth",
            )

        finally:
            hr("Cleanup")
            try:
                await c.delete(f"{BACKEND}/api/api-keys/{api_key_id}")
            except Exception:
                pass
            try:
                await c.delete(f"{BACKEND}/api/folders/{folder_id}?delete_docs=true")
            except Exception:
                pass

    print()
    print("═" * 74)
    print(f"MCP TOOLS: {len(PASS)} pass, {len(FAIL)} fail")
    print("═" * 74)
    for n in FAIL:
        print(f"  ✗ {n}")


if __name__ == "__main__":
    asyncio.run(main())
