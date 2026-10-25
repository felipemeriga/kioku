import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import promote
from release import bump_packages, channel

SHA = "a" * 40
HIVE_SHA = "b" * 40


class PromotionTests(unittest.TestCase):
    def exercise(
        self, verification_error=None, late_source_error=False, rehearsal=False
    ):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".release").mkdir()
            (root / "release-results").mkdir()
            (root / "hive").mkdir()
            plan = {
                "source_sha": SHA,
                "images": [{"package": "frontend"}],
                "versions": {"frontend": "1.2.3"},
                "cli": False,
            }
            env = {"RELEASE_SHA": SHA}
            if rehearsal:
                plan.update(
                    {"release_branch": "integration-test", "rehearsal_id": "run-1"}
                )
                env.update(
                    {"RELEASE_BRANCH": "integration-test", "RELEASE_PRERELEASE": "true"}
                )
            (root / ".release/pending.json").write_text(json.dumps(plan))

            def fake_git(*args, **kwargs):
                events.append(("git", *args))
                if args[:2] == ("rev-parse", "HEAD"):
                    return HIVE_SHA
                return ""

            def fake_process(args, **kwargs):
                events.append(tuple(args))
                code = (
                    1
                    if args[:3]
                    in (["gh", "release", "view"], ["git", "diff", "--cached"])
                    else 0
                )
                return subprocess.CompletedProcess(args, code, "", "")

            def verify(*args, **kwargs):
                events.append(("verified", args[1]))
                if verification_error:
                    raise verification_error
                return {"frontend": "deployment-id"}

            guards = iter(
                [None, RuntimeError("branch advanced") if late_source_error else None]
            )

            def guard(*args):
                events.append(("guard", *args[1:]))
                result = next(guards)
                if result:
                    raise result

            with (
                patch.dict(os.environ, env, clear=True),
                patch("promote.Path.cwd", return_value=root),
                patch("promote.configuration", return_value={}),
                patch("promote.update_hive"),
                patch("promote.git", side_effect=fake_git),
                patch("promote.subprocess.run", side_effect=fake_process),
                patch("promote.run", side_effect=lambda *args: events.append(args)),
                patch("promote.wait_for_deployments", side_effect=verify),
                patch("promote.assert_source_current", side_effect=guard),
            ):
                if verification_error or late_source_error:
                    with self.assertRaises(RuntimeError):
                        promote.main()
                else:
                    promote.main()
        return events

    def test_failed_deployment_preserves_drafts_and_never_marks_completed(self):
        events = self.exercise(verification_error=RuntimeError("deployment failed"))
        self.assertTrue(
            any(e[:3] == ("gh", "release", "create") and "--draft" in e for e in events)
        )
        self.assertFalse(any(e[:3] == ("gh", "release", "edit") for e in events))
        self.assertFalse(any(e[:3] == ("git", "tag", "-a") for e in events))

    def test_source_is_rechecked_after_uploads_before_hive_push(self):
        events = self.exercise(late_source_error=True)
        self.assertEqual(sum(e[0] == "guard" for e in events), 2)
        self.assertTrue(any(e[:3] == ("gh", "release", "upload") for e in events))
        self.assertFalse(any(e[:3] == ("git", "push", "origin") for e in events))

    def test_verification_precedes_publication_and_ledger_has_identity(self):
        events = self.exercise()
        verified = next(i for i, e in enumerate(events) if e[0] == "verified")
        published = next(
            i for i, e in enumerate(events) if e[:3] == ("gh", "release", "edit")
        )
        self.assertLess(verified, published)
        self.assertIn(("verified", HIVE_SHA), events)
        ledger = next(i for i, e in enumerate(events) if e[:3] == ("git", "tag", "-a"))
        self.assertTrue(
            any(
                e[:3] == ("git", "config", "user.email")
                for e in events[published:ledger]
            )
        )

    def test_branch_rehearsal_never_publishes_stable_or_writes_production_ledger(self):
        events = self.exercise(rehearsal=True)
        create = next(e for e in events if e[:3] == ("gh", "release", "create"))
        self.assertIn("frontend-v1.2.3-e2e.run-1", create)
        self.assertIn("--prerelease", create)
        self.assertIn("--latest=false", create)
        ledger = next(e for e in events if e[:3] == ("git", "tag", "-a"))
        self.assertEqual(ledger[3], "release/rehearsed-" + SHA)
        self.assertFalse(any("release/deployed-" in str(e) for e in events))

    def test_main_guard_fetches_nominated_branch_and_rejects_new_source(self):
        with patch("promote.git", side_effect=["", "different"]) as git:
            with self.assertRaises(RuntimeError):
                promote.assert_source_current(Path("/fixture"), SHA, "integration")
            self.assertEqual(
                git.call_args_list[0].args, ("fetch", "origin", "integration")
            )

    def test_rehearsal_requires_both_explicit_branch_and_opt_in(self):
        with self.assertRaises(ValueError):
            channel("feature", "run-1", {})
        with self.assertRaises(ValueError):
            channel("main", "run-1", {"RELEASE_PRERELEASE": "true"})
        self.assertEqual(
            channel("feature", "run-1", {"RELEASE_PRERELEASE": "true"}),
            "release/rehearsed-",
        )

    def test_shared_cli_version_file_updates_without_rewriting_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".release").mkdir()
            (root / ".release/versions.json").write_text("{}")
            (root / "cli/src/lib").mkdir(parents=True)
            (root / "cli/package.json").write_text('{"version":"0.4.0"}')
            (root / "cli/package-lock.json").write_text(
                '{"version":"0.4.0","packages":{"":{"version":"0.4.0"}}}'
            )
            (root / "cli/src/index.ts").write_text(
                'import { VERSION } from "./lib/version.js";'
            )
            (root / "cli/src/lib/version.ts").write_text(
                'export const VERSION = "0.4.0";'
            )
            bump_packages(root, ["cli"])
            self.assertIn('"0.4.1"', (root / "cli/src/lib/version.ts").read_text())
            self.assertEqual(
                (root / "cli/src/index.ts").read_text(),
                'import { VERSION } from "./lib/version.js";',
            )
