import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class InstallerTests(unittest.TestCase):
    def install(self, valid, version="1.2.3"):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            tools = root / "tools"
            tools.mkdir()
            marker = root / "executed"
            requests = root / "requests"
            payload = root / "payload"
            payload.write_text(f'#!/bin/sh\ntouch "{marker}"\necho kioku-test\n')
            checksum = (
                hashlib.sha256(payload.read_bytes()).hexdigest() if valid else "0" * 64
            )
            sums = root / "sums"
            sums.write_text(checksum + "  kioku-linux-x64\n")
            (tools / "uname").write_text(
                '#!/bin/sh\nif [ "$1" = -s ]; then echo Linux; else echo x86_64; fi\n'
            )
            (tools / "curl").write_text(
                f"#!{sys.executable}\n"
                "import os,sys,shutil\n"
                'url=next(a for a in sys.argv if a.startswith("https://"))\n'
                'with open(os.environ["FIXTURE_REQUESTS"],"a") as f: f.write(url+"\\n")\n'
                'if "api.github.com" in url: print(os.environ["FIXTURE_RELEASES"]); sys.exit(0)\n'
                'source=os.environ["FIXTURE_SUMS"] if url.endswith("SHA256SUMS") else os.environ["FIXTURE_PAYLOAD"]\n'
                'shutil.copyfile(source,sys.argv[sys.argv.index("-o")+1])\n'
            )
            for p in tools.iterdir():
                p.chmod(0o755)
            env = {
                **os.environ,
                "PATH": str(tools) + os.pathsep + os.environ["PATH"],
                "KIOKU_VERSION": version,
                "FIXTURE_REQUESTS": str(requests),
                "FIXTURE_RELEASES": '[\n{"tag_name": "cli-v1.2.4-e2e.123"},\n{"tag_name": "cli-v1.2.3"}\n]',
                "KIOKU_INSTALL_DIR": str(root / "install dir"),
                "FIXTURE_SUMS": str(sums),
                "FIXTURE_PAYLOAD": str(payload),
            }
            result = subprocess.run(
                ["sh", str(Path(__file__).with_name("install.sh"))],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(marker.exists(), valid)
            self.assertEqual((root / "install dir/kioku").exists(), valid)
            self.assertEqual(result.returncode == 0, valid, result.stderr)
            if valid:
                expected_version = version or "1.2.3"
                self.assertIn("/cli-v" + expected_version + "/", requests.read_text())
            if any(char in version for char in ("/", "?", ";", "\n", "\r")):
                self.assertFalse(requests.exists())

    def test_verified_download_installs_to_path_with_spaces(self):
        self.install(True)

    def test_explicit_prerelease_pin_is_supported(self):
        self.install(True, "1.2.3-e2e.20261024")

    def test_default_discovery_never_selects_a_prerelease(self):
        self.install(True, "")

    def test_pin_rejects_url_and_path_injection_before_network(self):
        for version in (
            "1.2.3/../../other",
            "1.2.3?token=x",
            "1.2.3;touch injected",
            "1.2.3\ninvalid",
            "1.2.3\r\n",
        ):
            self.install(False, version)

    def test_checksum_mismatch_never_executes_or_installs(self):
        self.install(False)


if __name__ == "__main__":
    unittest.main()
