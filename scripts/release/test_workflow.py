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
