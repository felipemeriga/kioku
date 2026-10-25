import ast
import re
import unittest
from pathlib import Path


class WorkflowTests(unittest.TestCase):
    def test_github_outputs_are_lines_not_literal_backslash_n(self):
        workflow = Path(".github/workflows/release.yml").read_text()
        constants = []
        for block in re.findall(
            r"python3 - <<'PY'\n(.*?)\n          PY", workflow, re.DOTALL
        ):
            code = "\n".join(line[10:] for line in block.splitlines())
            constants.extend(
                node.value
                for node in ast.walk(ast.parse(code))
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
            )
        self.assertIn("ready=true\n", constants)
        self.assertNotIn("ready=true\\n", constants)

    def test_read_only_build_jobs_do_not_persist_checkout_tokens(self):
        workflow = Path(".github/workflows/release.yml").read_text()
        images = workflow.split("  images:\n", 1)[1].split("  cli:\n", 1)[0]
        self.assertIn("persist-credentials: false", images)
        native = Path(".github/workflows/cli-native.yml").read_text()
        self.assertIn("persist-credentials: false", native)
        # Version and promotion jobs intentionally retain their scoped tokens.
        prepare = workflow.split("  prepare:\n", 1)[1].split("  validate:\n", 1)[0]
        self.assertNotIn("persist-credentials: false", prepare)

    def test_repo_rehearsal_requires_owner_manual_dispatch_and_dedicated_branch(self):
        ci = Path(".github/workflows/ci.yml").read_text()
        handler = ci.split("  release-e2e:\n", 1)[1]
        self.assertIn("github.event_name == 'workflow_dispatch'", handler)
        self.assertIn("inputs.release_e2e == true", handler)
        self.assertIn("github.actor == github.repository_owner", handler)
        self.assertIn("refs/heads/test/release-cd-e2e", handler)
        release = Path(".github/workflows/release.yml").read_text()
        self.assertIn("inputs.source_sha == github.sha", release)
        self.assertIn('git push origin "HEAD:$RELEASE_BRANCH"', release)
        self.assertIn("RELEASE_PRERELEASE:", release)
        self.assertNotIn("uses: ./.github/workflows/ci.yml", release)
        checks = Path(".github/workflows/checks.yml").read_text()
        self.assertNotIn("uses: ./.github/workflows/release.yml", checks)

    def test_native_matrix_and_cloud_only_images(self):
        workflow = Path(".github/workflows/release.yml").read_text()
        native = Path(".github/workflows/cli-native.yml").read_text()
        for target in (
            "linux-x64",
            "linux-arm64",
            "darwin-x64",
            "darwin-arm64",
            "windows-x64",
        ):
            self.assertIn("target: " + target, native)
        self.assertIn("driver: cloud", workflow)
        self.assertIn("file: ${{ matrix.dockerfile }}", workflow)
        self.assertIn("needs.retrieval-eval.result", workflow)
        self.assertNotIn("--force", workflow)


if __name__ == "__main__":
    unittest.main()
