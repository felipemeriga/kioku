import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from release import affected, bump, bump_packages, prepare, update_hive


class ReleaseTests(unittest.TestCase):
    def test_dependency_impact(self):
        self.assertEqual(affected(["backend/services/search.py"]), ["backend", "mcp"])
        self.assertEqual(affected(["cli/package-lock.json"]), ["cli", "mihari"])
        self.assertEqual(affected(["frontend/src/App.tsx"]), ["frontend"])
        self.assertEqual(affected(["mihari/mihari.py"]), ["mihari"])
        self.assertEqual(affected(["README.md", "docs/design.md"]), [])
        self.assertEqual(len(affected(["scripts/release/release.py"])), 5)

    def test_versions_patch_and_lockfiles_stay_consistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".release").mkdir()
            (root / ".release/versions.json").write_text(
                '{"mcp":"0.1.0","mihari":"0.1.0"}'
            )
            for package in ("frontend", "cli"):
                (root / package / "src").mkdir(parents=True)
                (root / package / "package.json").write_text('{"version":"1.2.3"}')
                (root / package / "package-lock.json").write_text(
                    '{"version":"1.2.3","packages":{"":{"version":"1.2.3"}}}'
                )
            (root / "cli/src/index.ts").write_text('const VERSION = "1.2.3";\n')
            (root / "backend").mkdir()
            (root / "backend/pyproject.toml").write_text(
                '[project]\nname = "backend"\nversion = "0.1.0"\n'
            )
            (root / "backend/uv.lock").write_text(
                '[[package]]\nname = "backend"\nversion = "0.1.0"\n\n[[package]]\nname = "other"\nversion = "4.0.0"\n'
            )
            result = bump_packages(
                root, ["frontend", "cli", "backend", "mcp", "mihari"]
            )
            self.assertEqual(result["cli"], "1.2.4")
            self.assertEqual(
                json.loads((root / "cli/package-lock.json").read_text())["packages"][
                    ""
                ]["version"],
                "1.2.4",
            )
            self.assertIn(
                'const VERSION = "1.2.4"', (root / "cli/src/index.ts").read_text()
            )
            self.assertIn(
                'name = "backend"\nversion = "0.1.1"',
                (root / "backend/uv.lock").read_text(),
            )
            self.assertIn(
                'name = "other"\nversion = "4.0.0"',
                (root / "backend/uv.lock").read_text(),
            )

    def test_invalid_version_rejected(self):
        with self.assertRaises(ValueError):
            bump("1.0.0-beta")

    def test_hive_updates_backend_and_worker_preserving_secrets_mounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            original = "services:\n  backend:\n    image: felipemeriga1/kioku-backend:latest\n    environment:\n      - AWS_SECRET_ACCESS_KEY=${AWS_SECRET_ACCESS_KEY}\n    volumes:\n      - /data:/data\n"
            for service in ("backend", "worker"):
                path = root / "kioku" / service / "docker-compose.yml"
                path.parent.mkdir(parents=True)
                path.write_text(original)
            image = {
                "package": "backend",
                "image": "felipemeriga1/kioku-backend",
                "tag": "0.1.1-abcdef",
            }
            result = {**image, "digest": "sha256:" + "a" * 64}
            update_hive(root, {"images": [image]}, [result])
            for service in ("backend", "worker"):
                text = (root / "kioku" / service / "docker-compose.yml").read_text()
                self.assertEqual(
                    text,
                    original.replace(":latest", ":0.1.1-abcdef@sha256:" + "a" * 64),
                )
            # Repeated application is byte-identical.
            update_hive(root, {"images": [image]}, [result])

    def test_hive_validation_is_atomic_and_rejects_missing_or_extra_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            p = root / "kioku/backend/docker-compose.yml"
            p.parent.mkdir(parents=True)
            p.write_text("    image: felipemeriga1/kioku-backend:latest\n")
            image = {
                "package": "backend",
                "image": "felipemeriga1/kioku-backend",
                "tag": "0.1.1",
            }
            result = {**image, "digest": "sha256:" + "b" * 64}
            with self.assertRaises(FileNotFoundError):
                update_hive(root, {"images": [image]}, [result])
            self.assertIn(":latest", p.read_text())
            for results in ([], [result, result], [{**result, "digest": "bad"}]):
                with self.assertRaises(ValueError):
                    update_hive(root, {"images": [image]}, results)

    def test_stale_trigger_skips_without_bump(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("release.git", side_effect=["", "new", "new", ""]),
        ):
            self.assertIsNone(prepare(Path(tmp), "old"))

    def test_retry_uses_same_version_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".release").mkdir()
            plan = {"source_sha": "old", "versions": {"cli": "1.0.1"}}
            (root / ".release/pending.json").write_text(json.dumps(plan))
            with patch(
                "release.git", side_effect=["", "releasecommit", "releasecommit", ""]
            ):
                self.assertEqual(prepare(root, "old"), plan)

    def test_completed_release_skips(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch(
                "release.git", side_effect=["", "head", "head", "release/deployed-head"]
            ),
        ):
            self.assertIsNone(prepare(Path(tmp), "head"))


if __name__ == "__main__":
    unittest.main()
