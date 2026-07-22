# tests/e2e/e2e_local_summary.py
"""E2E: the local-summary hook lifecycle — new folder needs generation,
saved summary is served fresh, stale summary needs regeneration."""
import os, sys, requests
from datetime import datetime, timedelta, timezone
from supabase import create_client

BACKEND = os.environ.get("BACKEND", "http://localhost:8000")
SUPABASE_URL = os.environ["SUPABASE_URL"]
ANON = os.environ.get("SUPABASE_ANON_KEY") or os.environ["SUPABASE_PUBLISHABLE_KEY"]
SVC = os.environ["SUPABASE_SERVICE_KEY"]
EMAIL = os.environ.get("E2E_EMAIL", "felipe.meriga@gmail.com")

checks = []
def check(name, cond):
    checks.append((name, cond)); print(("PASS" if cond else "FAIL"), name)

def session():
    admin = create_client(SUPABASE_URL, SVC)
    otp = admin.auth.admin.generate_link({"type": "magiclink", "email": EMAIL}).properties.email_otp
    anon = create_client(SUPABASE_URL, ANON)
    return anon.auth.verify_otp({"email": EMAIL, "token": otp, "type": "email"}).session

def main():
    sess = session()
    H = {"Authorization": f"Bearer {sess.access_token}"}
    admin = create_client(SUPABASE_URL, SVC)

    # Create a repo folder + mint an api key scoped to it.
    folder = requests.post(f"{BACKEND}/api/folders", headers=H,
                           json={"name": "e2e-localsum", "parent_id": None}).json()
    fid = folder["id"]
    requests.patch(f"{BACKEND}/api/folders/{fid}", headers=H, json={"kind": "repo"})
    key = requests.post(f"{BACKEND}/api/cli/mint-api-key", headers=H,
                        json={"scope_folder_id": fid, "name": "e2e-localsum"}).json()["key"]
    KH = {"Authorization": f"Bearer {key}"}

    # 1. New folder → needs generation.
    r = requests.get(f"{BACKEND}/api/cli/folder-summary", headers=KH, params={"folder_id": fid}).json()
    check("new folder needs_generation", r["needs_generation"] is True and r["sections"] is None)

    # 2. Save a summary via replace_folder_briefing → served fresh.
    # Note: the endpoint is PUT /api/folders/{id}/briefing (ReplaceBriefingRequest).
    # pin_all defaults to True so it is optional, but we include it for clarity.
    save_resp = requests.put(f"{BACKEND}/api/folders/{fid}/briefing", headers=H,
                             json={
                                 "sections": {
                                     "overview": "A test repo.",
                                     "architecture": "Monolith.",
                                 },
                                 "pin_all": True,
                             })
    check("briefing PUT 200", save_resp.status_code == 200)
    r2 = requests.get(f"{BACKEND}/api/cli/folder-summary", headers=KH, params={"folder_id": fid}).json()
    check("saved summary not stale", r2["needs_generation"] is False)
    check("summary sections returned", (r2["sections"] or {}).get("overview", {}).get("content") == "A test repo.")

    # 3. Backdate the row > 7 days → needs regeneration.
    admin.table("folder_summaries").update(
        {"generated_at": (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()}
    ).eq("folder_id", fid).execute()
    r3 = requests.get(f"{BACKEND}/api/cli/folder-summary", headers=KH, params={"folder_id": fid}).json()
    check("stale summary needs_generation", r3["needs_generation"] is True)

    # cleanup
    requests.delete(f"{BACKEND}/api/folders/{fid}", headers=H)

    failed = [n for n, ok in checks if not ok]
    print(f"\n{len(checks)-len(failed)}/{len(checks)} checks passed")
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
