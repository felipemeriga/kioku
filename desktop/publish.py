"""Verify signed installers and prepare the Tauri update manifest."""

import base64
import datetime
import json
import pathlib
import re
import subprocess
import tempfile
import tomllib


def manifest(root, version, public_key, verify=True):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid desktop version")
    platforms = {}
    for arch, target in [("arm64", "darwin-aarch64"), ("x64", "darwin-x86_64")]:
        name = f"Kioku-Alpha-{arch}.app.tar.gz"
        archives = list(root.rglob(name))
        signatures = list(root.rglob(name + ".sig"))
        if len(archives) != 1 or len(signatures) != 1:
            raise ValueError(f"Missing or ambiguous updater artifact for {arch}")
        signature = signatures[0].read_text().strip()
        decoded_signature = base64.b64decode(signature, validate=True)
        if verify:
            with tempfile.TemporaryDirectory() as temp:
                pub = pathlib.Path(temp) / "public.key"
                sig = pathlib.Path(temp) / "signature"
                pub.write_bytes(base64.b64decode(public_key, validate=True))
                sig.write_bytes(decoded_signature)
                subprocess.run(
                    [
                        "minisign",
                        "-Vm",
                        str(archives[0]),
                        "-p",
                        str(pub),
                        "-x",
                        str(sig),
                    ],
                    check=True,
                )
        platforms[target] = {
            "signature": signature,
            "url": f"https://github.com/felipemeriga/kioku/releases/download/desktop-v{version}/{name}",
        }
    return {
        "version": version,
        "notes": "Kioku desktop update",
        "pub_date": datetime.datetime.now(datetime.UTC).isoformat(),
        "platforms": platforms,
    }


if __name__ == "__main__":
    import sys

    config = json.loads(pathlib.Path("desktop/tauri.conf.json").read_text())
    package = tomllib.loads(pathlib.Path("desktop/Cargo.toml").read_text())
    if package["package"]["version"] != config["version"]:
        raise ValueError("Cargo and Tauri versions must match")
    root = pathlib.Path(sys.argv[1])
    result = manifest(root, config["version"], config["plugins"]["updater"]["pubkey"])
    (root / "latest.json").write_text(json.dumps(result, indent=2) + "\n")
