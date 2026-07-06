"""Performance E2E — hot-path latency budgets.

Each check measures p50 across 5 warmed runs (first run discarded to
account for cold-start caches). Budgets are generous — we fail loudly
if a regression pushes any hot path 2x over expected.
"""

from __future__ import annotations
import asyncio, os, statistics, sys, time
import httpx
from dotenv import load_dotenv
from supabase import create_client

load_dotenv("/Users/feliperamosdasilva/personal_projects/agentic-rag/backend/.env")
sys.path.insert(0, "/Users/feliperamosdasilva/personal_projects/agentic-rag/backend")

BACKEND = "http://localhost:8000"
SUPABASE_URL = os.environ["SUPABASE_URL"]
ANON = os.environ["SUPABASE_ANON_KEY"]

# SLO budgets (ms)
SLO = {
    "whoami":              (300,  "identity check"),
    "list_folders":        (500,  "sidebar tree data"),
    "briefing_get":        (800,  "briefing tab load"),
    "session_start_scope": (2000, "SessionStart hook 'scope-info' fetch"),
    "auth_config":         (500,  "CLI refresh preflight"),
    "cli_search":          (5000, "knowledge base search (embed + fanout)"),
}

PASS, FAIL = [], []
def check(n, cond, d=""):
    (PASS if cond else FAIL).append(n)
    print(f"  {'✓' if cond else '✗'} {n}" + (f" — {d[:200]}" if not cond else ""))
def hr(t): print(); print("═" * 74); print(f"  {t}"); print("═" * 74)


def get_token():
    admin = create_client(SUPABASE_URL, os.environ["SUPABASE_SERVICE_KEY"])
    otp = admin.auth.admin.generate_link({"type":"magiclink","email":"felipe.meriga@gmail.com"}).properties.email_otp
    anon = create_client(SUPABASE_URL, ANON)
    e = anon.auth.verify_otp({"email":"felipe.meriga@gmail.com","token":otp,"type":"email"})
    return e.session.access_token, e.user.id


async def measure(client: httpx.AsyncClient, method: str, path: str,
                    *, json_body: dict | None = None, warm: int = 1,
                    runs: int = 5, headers: dict | None = None) -> tuple[float, float, list[float]]:
    """Returns (p50_ms, p95_ms, all_ms)."""
    all_ms: list[float] = []
    for i in range(warm + runs):
        t0 = time.perf_counter()
        if method == "GET":
            r = await client.get(path, headers=headers)
        elif method == "POST":
            r = await client.post(path, json=json_body, headers=headers)
        else:
            raise ValueError(method)
        elapsed = (time.perf_counter() - t0) * 1000
        # Warm-up runs discarded
        if i >= warm:
            all_ms.append(elapsed)
        # Fail loudly if server error
        if r.status_code >= 500:
            raise RuntimeError(f"{method} {path} → {r.status_code}: {r.text[:200]}")
    p50 = statistics.median(all_ms)
    p95 = sorted(all_ms)[int(len(all_ms) * 0.95)] if len(all_ms) > 1 else all_ms[0]
    return p50, p95, all_ms


async def main():
    token, user_id = get_token()
    H = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=15, headers=H, base_url=BACKEND) as c:

        hr("Hot-path latency measurements (p50 across 5 runs, 1 warm-up)")

        # 1. whoami
        p50, p95, all_ms = await measure(c, "GET", "/api/cli/whoami")
        budget, desc = SLO["whoami"]
        check(f"whoami p50 < {budget}ms  ({desc})",
              p50 < budget,
              f"p50={p50:.0f}ms  p95={p95:.0f}ms  all={[f'{x:.0f}' for x in all_ms]}")

        # 2. list folders
        p50, p95, _ = await measure(c, "GET", "/api/folders")
        budget, desc = SLO["list_folders"]
        check(f"list folders p50 < {budget}ms  ({desc})",
              p50 < budget, f"p50={p50:.0f}ms p95={p95:.0f}ms")

        # 3. briefing GET on the agentic-rag folder (it's a repo)
        # Find its id
        from db.client import get_supabase
        sb = get_supabase()
        ar_row = (
            sb.table("folders").select("id, kind").eq("name","agentic-rag")
            .eq("user_id", user_id).limit(1).execute().data
        )
        if ar_row:
            fid = ar_row[0]["id"]
            if ar_row[0].get("kind") != "repo":
                sb.table("folders").update({"kind":"repo"}).eq("id", fid).eq(
                    "user_id", user_id).execute()
            p50, p95, _ = await measure(c, "GET", f"/api/folders/{fid}/briefing")
            budget, desc = SLO["briefing_get"]
            check(f"briefing GET p50 < {budget}ms  ({desc})",
                  p50 < budget, f"p50={p50:.0f}ms p95={p95:.0f}ms")

            # 4. session-start scope-info via an api key
            r = await c.post("/api/api-keys",
                              json={"name": "perf-probe",
                                    "scope_folder_id": fid})
            apik = r.json()["key"]
            apik_id = r.json()["id"]
            H_key = {"Authorization": f"Bearer {apik}"}
            p50, p95, _ = await measure(
                c, "GET", "/api/cli/scope-info",
                headers=H_key,
            )
            budget, desc = SLO["session_start_scope"]
            check(f"scope-info p50 < {budget}ms  ({desc})",
                  p50 < budget, f"p50={p50:.0f}ms p95={p95:.0f}ms")

            # 5. auth-config (unauthenticated, tiny)
            p50, p95, _ = await measure(
                c, "GET", "/api/cli/auth-config", headers={},
            )
            budget, desc = SLO["auth_config"]
            check(f"auth-config p50 < {budget}ms  ({desc})",
                  p50 < budget, f"p50={p50:.0f}ms p95={p95:.0f}ms")

            # 6. cli search — hits embed + fanout
            search_body = {"query": "how does deploy work", "limit": 5}
            p50, p95, _ = await measure(
                c, "POST", "/api/cli/search",
                json_body=search_body, headers=H_key, warm=1, runs=3,
            )
            budget, desc = SLO["cli_search"]
            check(f"cli search p50 < {budget}ms  ({desc})",
                  p50 < budget, f"p50={p50:.0f}ms p95={p95:.0f}ms")

            # Cleanup
            await c.delete(f"/api/api-keys/{apik_id}")

    print()
    print("═" * 74)
    print(f"PERFORMANCE: {len(PASS)} pass, {len(FAIL)} fail")
    print("═" * 74)
    for n in FAIL: print(f"  ✗ {n}")


if __name__ == "__main__":
    asyncio.run(main())
