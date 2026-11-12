import base64
import pathlib
import tempfile
import unittest

from publish import manifest


class ManifestTests(unittest.TestCase):
    def test_requires_both_signed_architectures_and_valid_versions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            with self.assertRaises(ValueError):
                manifest(root, "0.2.0", "", verify=False)
            for arch in ["arm64", "x64"]:
                name = f"Kioku-Alpha-{arch}.app.tar.gz"
                (root / name).write_bytes(b"fixture")
                (root / (name + ".sig")).write_text(
                    base64.b64encode(b"fixture signature").decode()
                )
            result = manifest(root, "0.2.0", "", verify=False)
            self.assertEqual(
                set(result["platforms"]), {"darwin-aarch64", "darwin-x86_64"}
            )
            self.assertIn(
                "desktop-v0.2.0/", result["platforms"]["darwin-aarch64"]["url"]
            )
            with self.assertRaises(ValueError):
                manifest(root, "../../bad", "", verify=False)
            (root / "Kioku-Alpha-x64.app.tar.gz.sig").write_text("not base64")
            with self.assertRaises(ValueError):
                manifest(root, "0.2.0", "", verify=False)


if __name__ == "__main__":
    unittest.main()
