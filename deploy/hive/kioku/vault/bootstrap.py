#!/usr/bin/env python3
"""Bootstrap only a new isolated Kioku vault, capturing credentials privately."""

import json
import os
import secrets
import subprocess
from pathlib import Path
import argparse

parser = argparse.ArgumentParser(
    description="Bootstrap a new private vault; values stay in protected files."
)
parser.add_argument("--directory", type=Path, required=True)
parser.add_argument("--recovery-directory", type=Path, required=True)
args = parser.parse_args()
root = args.directory
recovery = args.recovery_directory
recovery.mkdir(mode=0o700, parents=True, exist_ok=True)
recovery.chmod(0o700)
if recovery.resolve() == root.resolve():
    raise SystemExit("Recovery material must use a separate directory")


def save(name, data):
    p = recovery / name
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(json.dumps(data))


def call(method, path, body=None, token=None):
    code = "let s='';process.stdin.on('data',b=>s+=b);process.stdin.on('end',async()=>{const r=JSON.parse(s);try{const p=await fetch('http://127.0.0.1:8080'+r.path,{method:r.method,headers:{'Content-Type':'application/json',...(r.token?{Authorization:'Bearer '+r.token}:{})},...(r.body?{body:JSON.stringify(r.body)}:{})});process.stdout.write(JSON.stringify({status:p.status,data:await p.json()}))}catch(e){process.stdout.write(JSON.stringify({status:0}))}})"
    r = subprocess.run(
        ["docker", "exec", "-i", "kioku-vault", "node", "-e", code],
        input=json.dumps(
            {"method": method, "path": path, "body": body, "token": token}
        ),
        text=True,
        capture_output=True,
        timeout=60,
        check=True,
    )
    response = json.loads(r.stdout)
    if response["status"] not in (200, 201):
        save("failure-" + secrets.token_hex(4) + ".json", response)
        raise RuntimeError(
            "Provider bootstrap request failed: "
            + method
            + " "
            + path
            + " status="
            + str(response["status"])
            + "; private diagnostics saved"
        )
    return response["data"]


if (recovery / "bootstrap.json").exists():
    boot = json.loads((recovery / "bootstrap.json").read_text())
else:
    password = secrets.token_urlsafe(40) + "Aa1!"
    save(
        "administrator.json",
        {"email": "vault-admin@kioku.internal", "password": password},
    )
    boot = call(
        "POST",
        "/api/v1/admin/bootstrap",
        {
            "email": "vault-admin@kioku.internal",
            "password": password,
            "organization": "Kioku Vault",
        },
    )
    save("bootstrap.json", boot)
token = boot["identity"]["credentials"]["token"]
org = boot["organization"]["id"]
if (recovery / "project.json").exists():
    project = json.loads((recovery / "project.json").read_text())
else:
    project = call(
        "POST",
        "/api/v1/projects",
        {
            "projectName": "Kioku credentials",
            "projectDescription": "Private root-scoped Kioku credential bundles",
            "slug": "kioku-credentials",
            "type": "secret-manager",
            "template": "default",
        },
        token,
    )["project"]
    save("project.json", project)
if (recovery / "service-identity.json").exists():
    identity = json.loads((recovery / "service-identity.json").read_text())
else:
    identity = call(
        "POST",
        "/api/v1/identities",
        {
            "name": "Kioku backend credential adapter",
            "organizationId": org,
            "role": "no-access",
        },
        token,
    )["identity"]
    save("service-identity.json", identity)
if not (recovery / "membership.json").exists():
    save(
        "membership.json",
        call(
            "POST",
            f"/api/v1/projects/{project['id']}/memberships/identities/{identity['id']}",
            {"roles": [{"role": "member"}]},
            token,
        ),
    )
if (recovery / "universal-auth.json").exists():
    ua = json.loads((recovery / "universal-auth.json").read_text())
else:
    ua = call(
        "POST",
        f"/api/v1/auth/universal-auth/identities/{identity['id']}",
        {"accessTokenTTL": 300, "accessTokenMaxTTL": 300},
        token,
    )
    save("universal-auth.json", ua)
if (recovery / "client-secret.json").exists():
    secret = json.loads((recovery / "client-secret.json").read_text())
else:
    secret = call(
        "POST",
        f"/api/v1/auth/universal-auth/identities/{identity['id']}/client-secrets",
        {"description": "Kioku backend only"},
        token,
    )
    save("client-secret.json", secret)
# Print shapes only while validating provider-version contract.
print("Bootstrap completed; secret response keys:", list(secret))
client = ua["identityUniversalAuth"]["clientId"]
client_secret = secret.get("clientSecret")
if isinstance(client_secret, dict):
    client_secret = client_secret.get("secret")
if not isinstance(client_secret, str):
    raise RuntimeError("Unexpected client secret response shape")
values = dict(
    line.split("=", 1)
    for line in (root / "vault.env").read_text().splitlines()
    if "=" in line
)
config = {
    "KIOKU_VAULT_URL": "http://kioku-vault:8080",
    "KIOKU_VAULT_ALLOW_INTERNAL_HTTP": "true",
    "KIOKU_VAULT_PROJECT_ID": project["id"],
    "KIOKU_VAULT_ENVIRONMENT": "prod",
    "KIOKU_VAULT_CLIENT_ID": client,
    "KIOKU_VAULT_CLIENT_SECRET": client_secret,
    "KIOKU_VAULT_WRITE_HMAC_KEY": values["KIOKU_VAULT_WRITE_HMAC_KEY"],
}
p = root / "backend-vault.env"
fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as f:
    f.write("".join(k + "=" + v + "\n" for k, v in config.items()))
# Independent recovery copy; DB backup excludes these encryption keys.
save(
    "encryption-material.json",
    {
        "ENCRYPTION_KEY": values["ENCRYPTION_KEY"],
        "AUTH_SECRET": values["AUTH_SECRET"],
        "KIOKU_VAULT_WRITE_HMAC_KEY": values["KIOKU_VAULT_WRITE_HMAC_KEY"],
    },
)
print(
    "Dedicated no-access-org/project-member machine identity configured; backend env file written privately. No live Kioku env changed."
)
