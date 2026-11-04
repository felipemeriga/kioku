import copy
import unittest
from unittest.mock import patch

import bootstrap

SHA = "a" * 40
CONFIG = {
    "url": "https://dokploy.example",
    "key": "fixture-only",
    "ids": {"tsukai": bootstrap.COMPOSE_ID},
}
PLAN = {
    "images": [
        {
            "package": "tsukai",
            "image": "felipemeriga1/kioku-tsukai",
            "tag": "0.1.1-source",
        }
    ]
}
RESULTS = [
    {
        "package": "tsukai",
        "image": "felipemeriga1/kioku-tsukai",
        "digest": "sha256:" + "b" * 64,
    }
]


class Dokploy:
    def __init__(self):
        self.compose = {
            "composeId": bootstrap.COMPOSE_ID,
            "name": "tsukai",
            "appName": "kioku-tsukai-runner",
            "composePath": bootstrap.PATH,
            "sourceType": "github",
            "composeType": "docker-compose",
            "owner": "felipemeriga",
            "repository": "hive",
            "branch": "main",
            "serverId": None,
            "description": bootstrap.DESCRIPTION,
            "autoDeploy": False,
            "composeStatus": "idle",
        }
        self.records, self.containers, self.calls = [], [], []
        self.lose_response = False

    def __call__(self, path, payload=None, **query):
        self.calls.append((path, payload, query))
        if path == "compose.one":
            return copy.deepcopy(self.compose)
        if path == "deployment.allByCompose":
            return self.records
        if path.startswith("docker."):
            return self.containers
        if path == "compose.update":
            self.compose.update(payload)
            return copy.deepcopy(self.compose)
        if path == "compose.deploy":
            if self.lose_response:
                raise RuntimeError("ambiguous transport outcome")
            return {"success": True}
        raise AssertionError(path)


class BootstrapTests(unittest.TestCase):
    def start(self, api):
        with (
            patch("bootstrap.initial_image", return_value=True),
            patch("bootstrap.git", return_value=SHA),
        ):
            return bootstrap.start("hive", SHA, PLAN, RESULTS, CONFIG, call=api)

    def test_first_launch_is_claimed_once_and_enabled_only_after_real_commit_proof(
        self,
    ):
        api = Dokploy()
        self.assertTrue(self.start(api))
        self.assertFalse(api.compose["autoDeploy"])
        posts = [(path, data) for path, data, _ in api.calls if data]
        self.assertEqual([p for p, _ in posts], ["compose.update", "compose.deploy"])
        self.assertNotIn(
            "description", posts[1][1]
        )  # Correlation is not cloned commit proof.
        self.assertTrue(self.start(api))
        self.assertEqual(sum(p == "compose.deploy" for p, _, _ in api.calls), 1)
        with self.assertRaises(RuntimeError):
            bootstrap.finish(SHA, CONFIG, {}, call=api)
        self.assertFalse(api.compose["autoDeploy"])
        bootstrap.finish(SHA, CONFIG, {"tsukai": "exact-verified-deployment"}, call=api)
        self.assertTrue(api.compose["autoDeploy"])
        self.assertEqual(api.compose["watchPaths"], ["kioku/tsukai/**"])
        # Enabling and narrowing the webhook occur in the same update: there is
        # no enabled interval with Dokploy's null/empty "all changes" filter.
        activation = api.calls[-1]
        self.assertEqual(activation[0], "compose.update")
        self.assertTrue(activation[1]["autoDeploy"])
        self.assertEqual(activation[1]["watchPaths"], ["kioku/tsukai/**"])
        api.records = [{"description": "Commit: " + SHA, "status": "done"}]
        api.compose["autoDeploy"] = (
            False  # Subsequent human disable must survive reruns.
        )
        self.assertFalse(self.start(api))
        self.assertFalse(api.compose["autoDeploy"])
        self.assertEqual(sum(p == "compose.deploy" for p, _, _ in api.calls), 1)

    def test_lost_queue_response_is_never_blindly_reposted(self):
        api = Dokploy()
        api.lose_response = True
        with self.assertRaises(RuntimeError):
            self.start(api)
        self.assertTrue(
            self.start(api)
        )  # Existing verifier will reconcile or time out.
        self.assertEqual(sum(p == "compose.deploy" for p, _, _ in api.calls), 1)
        self.assertFalse(api.compose["autoDeploy"])

    def test_noninitial_services_never_call_dokploy(self):
        api = Dokploy()
        with patch("bootstrap.initial_image", return_value=False):
            self.assertFalse(
                bootstrap.start("hive", SHA, PLAN, RESULTS, CONFIG, call=api)
            )
        self.assertEqual(api.calls, [])

    def test_unrelated_or_used_or_running_services_cannot_be_activated(self):
        changes = [
            {"composeId": "other"},
            {"composePath": "kioku/backend/docker-compose.yml"},
            {"repository": "other"},
            {"branch": "develop"},
            {"owner": "other"},
            {"sourceType": "raw"},
            {"composeType": "stack"},
            {"serverId": "remote"},
            {"autoDeploy": True},
            {"description": "human disabled"},
            {"composeStatus": "running"},
        ]
        for change in changes:
            with self.subTest(change=change):
                api = Dokploy()
                api.compose.update(change)
                with self.assertRaises((ValueError, RuntimeError)):
                    self.start(api)
                self.assertFalse(any(data for _, data, _ in api.calls))
        for field in ("records", "containers"):
            api = Dokploy()
            setattr(api, field, [{"existing": True}])
            with self.assertRaises(RuntimeError):
                self.start(api)
            self.assertFalse(any(data for _, data, _ in api.calls))

    def test_changed_claim_cannot_enable_another_service(self):
        api = Dokploy()
        self.start(api)
        api.compose["description"] = "human changed"
        with self.assertRaises(RuntimeError):
            bootstrap.finish(SHA, CONFIG, {"tsukai": "deployment"}, call=api)
        self.assertFalse(api.compose["autoDeploy"])

    def test_image_transition_requires_exact_bootstrap_parent_and_verified_digest(self):
        before = f"services:\n  tsukai:\n    image: {bootstrap.BOOTSTRAP}\n"
        after = (
            "    image: felipemeriga1/kioku-tsukai:0.1.1-source@"
            + RESULTS[0]["digest"]
            + "\n"
        )
        with patch("bootstrap.git", side_effect=[before, after]):
            self.assertTrue(bootstrap.initial_image("hive", SHA, PLAN, RESULTS))
        with patch("bootstrap.git", return_value=after):
            self.assertFalse(bootstrap.initial_image("hive", SHA, PLAN, RESULTS))
        with patch(
            "bootstrap.git", side_effect=[before, after.replace("b" * 64, "c" * 64)]
        ):
            with self.assertRaises(ValueError):
                bootstrap.initial_image("hive", SHA, PLAN, RESULTS)
        with (
            patch("bootstrap.initial_image", return_value=True),
            patch("bootstrap.git", return_value="c" * 40),
        ):
            with self.assertRaisesRegex(RuntimeError, "Hive advanced"):
                bootstrap.start("hive", SHA, PLAN, RESULTS, CONFIG, call=Dokploy())
