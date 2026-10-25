import unittest

from deployment import (
    affected_services,
    configuration,
    record_commit,
    wait_for_deployments,
)

SHA = "a" * 40
OTHER = "b" * 40
PLAN = {"images": [{"package": "backend"}, {"package": "frontend"}]}
CONFIG = {"ids": {"backend": "b", "worker": "w", "frontend": "f"}, "timeout": 10}


def record(sha=SHA, status="done", time="2026-10-24T10:00:00Z", marker="Commit"):
    return {
        "deploymentId": "deployment-1",
        "createdAt": time,
        "description": f"{marker}: {sha}",
        "status": status,
    }


class DeploymentTests(unittest.TestCase):
    def test_backend_includes_worker_and_cli_only_needs_no_config(self):
        self.assertEqual(affected_services(PLAN), ["backend", "frontend", "worker"])
        self.assertIsNone(configuration({"images": []}, {}))
        self.assertEqual(wait_for_deployments({"images": []}, SHA), {})

    def test_config_requires_all_service_ids_and_https(self):
        env = {
            "DOKPLOY_URL": "https://dokploy.example",
            "DOKPLOY_API_KEY": "test-only",
            "DOKPLOY_COMPOSE_IDS": '{"backend":"b","worker":"w","frontend":"f"}',
        }
        self.assertEqual(configuration(PLAN, env)["timeout"], 900)
        for replacement in (
            {"DOKPLOY_URL": "http://example"},
            {"DOKPLOY_API_KEY": ""},
            {"DOKPLOY_COMPOSE_IDS": '{"backend":"b"}'},
            {"DOKPLOY_DEPLOY_TIMEOUT_SECONDS": "0"},
        ):
            with self.assertRaises(ValueError):
                configuration(PLAN, {**env, **replacement})

    def test_both_dokploy_markers_match_full_sha_only(self):
        for marker in ("Hash", "Commit"):
            self.assertEqual(record_commit(record(marker=marker)), SHA)
        for value in (
            f"Commit: {SHA[:12]}",
            f"Commit: {SHA}extra",
            f"prefix Commit: {SHA}",
        ):
            self.assertIsNone(record_commit({"description": value}))

    def test_all_affected_services_must_finish_exact_commit(self):
        calls = []

        def fetch(compose):
            calls.append(compose)
            return [record(marker="Hash")]

        proof = wait_for_deployments(
            PLAN, SHA, config=CONFIG, fetch=fetch, clock=lambda: 0
        )
        self.assertEqual(set(proof), {"backend", "worker", "frontend"})
        self.assertEqual(set(calls), {"b", "w", "f"})

    def test_other_commit_done_does_not_satisfy_gate(self):
        ticks = iter([0, 11])
        with self.assertRaises(TimeoutError):
            wait_for_deployments(
                PLAN,
                SHA,
                config=CONFIG,
                fetch=lambda _: [record(OTHER)],
                clock=lambda: next(ticks),
            )

    def test_failure_or_unknown_status_fails_closed(self):
        for status in ("error", "cancelled", "unexpected"):
            with self.assertRaises(RuntimeError):
                wait_for_deployments(
                    PLAN,
                    SHA,
                    config=CONFIG,
                    fetch=lambda _, status=status: [record(status=status)],
                    clock=lambda: 0,
                )

    def test_newer_deployment_supersedes_old_done_record(self):
        records = [record(), record(OTHER, time="2026-10-24T11:00:00Z")]
        with self.assertRaisesRegex(RuntimeError, "superseded"):
            wait_for_deployments(
                PLAN, SHA, config=CONFIG, fetch=lambda _: records, clock=lambda: 0
            )

    def test_pending_eventually_completes(self):
        responses = iter(
            [[record(status="queued")], [record(status="running")], [record()]]
        )
        plan = {"images": [{"package": "frontend"}]}
        sleeps = []
        proof = wait_for_deployments(
            plan,
            SHA,
            config=CONFIG,
            fetch=lambda _: next(responses),
            clock=lambda: 0,
            sleep=sleeps.append,
        )
        self.assertEqual(len(sleeps), 2)
        self.assertEqual(proof, {"frontend": "deployment-1"})

    def test_api_error_never_counts_as_verified(self):
        def fail(_):
            raise RuntimeError("HTTP 401")

        with self.assertRaises(RuntimeError):
            wait_for_deployments(PLAN, SHA, config=CONFIG, fetch=fail)
        with self.assertRaises(ValueError):
            wait_for_deployments(PLAN, SHA, config=CONFIG, fetch=lambda _: {})
