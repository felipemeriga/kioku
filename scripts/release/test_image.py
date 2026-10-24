import json
import subprocess
import unittest
from unittest.mock import Mock

from image import existing_digest, revision

SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64


def response(value, code=0, error=""):
    return subprocess.CompletedProcess([], code, json.dumps(value), error)


class ImageTests(unittest.TestCase):
    def test_reuse_requires_exact_revision_and_reads_config_by_digest(self):
        inspect = Mock(
            side_effect=[
                response({"digest": DIGEST}),
                response(
                    {"config": {"Labels": {"org.opencontainers.image.revision": SHA}}}
                ),
            ]
        )
        self.assertEqual(existing_digest("example/image:1.0.0", SHA, inspect), DIGEST)
        self.assertIn("example/image@" + DIGEST, inspect.call_args_list[1].args[0])

    def test_wrong_or_missing_revision_rejected(self):
        for labels in ({}, {"org.opencontainers.image.revision": "c" * 40}):
            inspect = Mock(
                side_effect=[
                    response({"digest": DIGEST}),
                    response({"config": {"Labels": labels}}),
                ]
            )
            with self.assertRaises(ValueError):
                existing_digest("image:1.0.0", SHA, inspect)

    def test_missing_tag_can_build_but_registry_errors_cannot_overwrite(self):
        self.assertIsNone(
            existing_digest(
                "image:1", SHA, Mock(return_value=response({}, 1, "manifest unknown"))
            )
        )
        for error in ("unauthorized", "toomanyrequests", "network timeout"):
            with self.assertRaises(RuntimeError):
                existing_digest(
                    "image:1", SHA, Mock(return_value=response({}, 1, error))
                )

    def test_platform_index_config_supported(self):
        config = {
            "linux/amd64": {
                "config": {"Labels": {"org.opencontainers.image.revision": SHA}}
            }
        }
        self.assertEqual(revision(config), SHA)
