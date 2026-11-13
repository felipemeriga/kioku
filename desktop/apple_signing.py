"""Production gates for the Kioku Apple signing team and notarized installers."""

import argparse
import base64
import json
import os
import pathlib
import re
import subprocess
import tempfile
import uuid

TEAM = "KFCS65DU8T"


def validate_credentials(env):
    required = (
        "APPLE_CERTIFICATE",
        "APPLE_CERTIFICATE_PASSWORD",
        "APPLE_SIGNING_IDENTITY",
        "APPLE_API_KEY",
        "APPLE_API_ISSUER",
        "APPLE_API_KEY_P8",
    )
    missing = [name for name in required if not env.get(name)]
    if missing:
        raise ValueError("Missing production Apple credentials: " + ", ".join(missing))
    if not re.fullmatch(
        rf"Developer ID Application: [^\r\n]+ \({TEAM}\)",
        env["APPLE_SIGNING_IDENTITY"],
    ):
        raise ValueError(
            "Signing identity must be Developer ID Application for " + TEAM
        )
    try:
        certificate = base64.b64decode(env["APPLE_CERTIFICATE"], validate=True)
    except ValueError:
        raise ValueError(
            "APPLE_CERTIFICATE must contain a base64 PKCS#12 export"
        ) from None
    if not certificate:
        raise ValueError("APPLE_CERTIFICATE must not be empty")
    if not re.fullmatch(r"[A-Za-z0-9]{10,64}", env["APPLE_API_KEY"]):
        raise ValueError("Invalid APPLE_API_KEY identifier")
    try:
        uuid.UUID(env["APPLE_API_ISSUER"])
    except ValueError:
        raise ValueError("APPLE_API_ISSUER must be a UUID") from None
    key = env["APPLE_API_KEY_P8"].strip()
    if not key.startswith("-----BEGIN PRIVATE KEY-----") or not key.endswith(
        "-----END PRIVATE KEY-----"
    ):
        raise ValueError("APPLE_API_KEY_P8 must contain a PKCS#8 private key")


def prepare(env):
    validate_credentials(env)
    root = pathlib.Path(env["RUNNER_TEMP"]).resolve()
    if root.is_relative_to(pathlib.Path.cwd().resolve()):
        raise ValueError("Signing credentials must be stored outside the repository")
    directory = pathlib.Path(tempfile.mkdtemp(prefix="kioku-notary-", dir=root))
    key = directory / "AuthKey.p8"
    with open(key, "x", opener=lambda path, flags: os.open(path, flags, 0o600)) as file:
        file.write(env["APPLE_API_KEY_P8"].strip() + "\n")
    result = subprocess.run(
        ["openssl", "pkey", "-in", str(key), "-noout"], capture_output=True, check=False
    )
    if result.returncode:
        key.unlink(missing_ok=True)
        directory.rmdir()
        raise ValueError("The Apple notarization private key could not be parsed")
    with pathlib.Path(env["GITHUB_ENV"]).open("a") as file:
        file.write(f"APPLE_API_KEY_PATH={key}\n")
    return key


def cleanup(env):
    key = pathlib.Path(env.get("APPLE_API_KEY_PATH", "")).resolve()
    root = pathlib.Path(env["RUNNER_TEMP"]).resolve()
    if (
        key.is_relative_to(root)
        and key.name == "AuthKey.p8"
        and key.parent.name.startswith("kioku-notary-")
    ):
        key.unlink(missing_ok=True)
        key.parent.rmdir()


def validate_signature(details):
    if not re.search(rf"^TeamIdentifier={TEAM}$", details, re.MULTILINE):
        raise ValueError("The installer is not signed by the expected Apple team")
    if not re.search(r"^Authority=Developer ID Application:", details, re.MULTILINE):
        raise ValueError("A Developer ID Application signature is required")
    flags = re.search(r"\bflags=0x([0-9a-fA-F]+)", details)
    if not flags or not int(flags[1], 16) & 0x10000:
        raise ValueError("The application must enable hardened runtime")


def verify(bundle, env):
    app = bundle / "macos" / "Kioku Alpha.app"
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    details = subprocess.run(
        ["codesign", "-d", "--verbose=4", str(app)],
        capture_output=True,
        text=True,
        check=True,
    )
    validate_signature(details.stdout + details.stderr)
    subprocess.run(["xcrun", "stapler", "validate", str(app)], check=True)
    subprocess.run(["spctl", "--assess", "--type", "execute", str(app)], check=True)
    images = list((bundle / "dmg").glob("*.dmg"))
    if len(images) != 1:
        raise ValueError("Expected exactly one signed DMG for this architecture")
    image = images[0]
    subprocess.run(["codesign", "--verify", "--strict", str(image)], check=True)
    result = subprocess.run(
        [
            "xcrun",
            "notarytool",
            "submit",
            str(image),
            "--key",
            env["APPLE_API_KEY_PATH"],
            "--key-id",
            env["APPLE_API_KEY"],
            "--issuer",
            env["APPLE_API_ISSUER"],
            "--wait",
            "--timeout",
            "20m",
            "--output-format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        status = json.loads(result.stdout)
    except ValueError:
        raise ValueError("Apple did not return a notarization result") from None
    if result.returncode or status.get("status") != "Accepted":
        raise ValueError(
            "DMG notarization was not accepted; request "
            + str(status.get("id", "unknown"))
        )
    subprocess.run(["xcrun", "stapler", "staple", str(image)], check=True)
    subprocess.run(["xcrun", "stapler", "validate", str(image)], check=True)
    subprocess.run(
        [
            "spctl",
            "--assess",
            "--type",
            "open",
            "--context",
            "context:primary-signature",
            str(image),
        ],
        check=True,
    )
    print("Verified Apple team, hardened runtime and notarized app/DMG for", TEAM)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "verify", "cleanup"])
    args = parser.parse_args()
    if args.action == "prepare":
        print(prepare(os.environ))
    elif args.action == "verify":
        verify(pathlib.Path("desktop/target/release/bundle"), os.environ)
    else:
        cleanup(os.environ)
