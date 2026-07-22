# tests/e2e/e2e_cli_login.py
"""E2E: CLI browser-handoff login. Simulates the browser 'complete' with a
real Supabase session and drives the device poll to completion."""
import os
import sys
import requests
from supabase import create_client

BACKEND = os.environ.get("BACKEND", "http://localhost:8000")
SUPABASE_URL = os.environ["SUPABASE_URL"]
ANON = os.environ.get("SUPABASE_ANON_KEY") or os.environ["SUPABASE_PUBLISHABLE_KEY"]
EMAIL = os.environ.get("E2E_EMAIL", "felipe.meriga@gmail.com")

checks = []
def check(name, cond):
    checks.append((name, cond))
    print(("PASS" if cond else "FAIL"), name)

def get_session():
    admin = create_client(SUPABASE_URL, os.environ["SUPABASE_SERVICE_KEY"])
    otp = admin.auth.admin.generate_link({"type": "magiclink", "email": EMAIL}).properties.email_otp
    anon = create_client(SUPABASE_URL, ANON)
    e = anon.auth.verify_otp({"email": EMAIL, "token": otp, "type": "email"})
    return e.session

def main():
    # 1. CLI start
    r = requests.post(f"{BACKEND}/api/cli/auth/device/start",
                      json={"hostname": "e2e-box", "os": "linux"})
    check("start 200", r.status_code == 200)
    body = r.json()
    check("verification_url has req", body["request_id"] in body["verification_url"])
    dev = body["device_code"]

    # 2. info shows device, no secrets
    info = requests.get(f"{BACKEND}/api/cli/auth/device/info",
                        params={"req": body["request_id"]}).json()
    check("info hostname", info["hostname"] == "e2e-box")
    check("info valid", info["valid"] is True)

    # 3. poll pending -> 428
    p = requests.post(f"{BACKEND}/api/cli/auth/device/token", json={"device_code": dev})
    check("poll pending 428", p.status_code == 428)

    # 4. browser completes with a real session
    sess = get_session()
    c = requests.post(f"{BACKEND}/api/cli/auth/device/complete",
                      headers={"Authorization": f"Bearer {sess.access_token}"},
                      json={"request_id": body["request_id"],
                            "refresh_token": sess.refresh_token,
                            "expires_at": sess.expires_at,
                            "email": EMAIL})
    check("complete 200", c.status_code == 200)

    # 5. poll authorized -> tokens
    p2 = requests.post(f"{BACKEND}/api/cli/auth/device/token", json={"device_code": dev})
    check("poll authorized 200", p2.status_code == 200)
    tok = p2.json()
    check("tokens present", bool(tok.get("access_token")) and tok["user"]["email"] == EMAIL)

    # 6. token works against whoami
    w = requests.get(f"{BACKEND}/api/cli/whoami",
                     headers={"Authorization": f"Bearer {tok['access_token']}"})
    check("whoami with new token 200", w.status_code == 200)

    # 7. single-use: second poll -> 410
    p3 = requests.post(f"{BACKEND}/api/cli/auth/device/token", json={"device_code": dev})
    check("single-use 410", p3.status_code == 410)

    failed = [n for n, ok in checks if not ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
    sys.exit(1 if failed else 0)

if __name__ == "__main__":
    main()
