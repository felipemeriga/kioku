"""Verify Dokploy completed the exact promoted Hive commit before publication."""

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

SHA = re.compile(r"[0-9a-f]{40}\Z")
COMMIT = re.compile(r"(?:Commit|Hash): ([0-9a-f]{40})\s*\Z")


def affected_services(plan):
    services = set()
    for image in plan["images"]:
        package = image["package"]
        services.update(("backend", "worker") if package == "backend" else (package,))
    return sorted(services)


def configuration(plan, environ=None):
    services = affected_services(plan)
    if not services:
        return None
    env = os.environ if environ is None else environ
    url = env.get("DOKPLOY_URL", "").rstrip("/")
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "DOKPLOY_URL must be an HTTPS origin without credentials or a path"
        )
    key = env.get("DOKPLOY_API_KEY", "")
    if not key:
        raise ValueError("DOKPLOY_API_KEY is required for deployment verification")
    mapping = json.loads(env.get("DOKPLOY_COMPOSE_IDS", "{}"))
    if not isinstance(mapping, dict) or any(
        not isinstance(mapping.get(service), str) or not mapping[service].strip()
        for service in services
    ):
        raise ValueError(
            "DOKPLOY_COMPOSE_IDS must map every affected service to its Compose ID"
        )
    timeout = int(env.get("DOKPLOY_DEPLOY_TIMEOUT_SECONDS", "900"))
    if not 1 <= timeout <= 3600:
        raise ValueError("DOKPLOY_DEPLOY_TIMEOUT_SECONDS must be between 1 and 3600")
    return {"url": url, "key": key, "ids": mapping, "timeout": timeout}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the API credential to a redirect destination.
        return None


def fetch_deployments(config, compose_id):
    query = urllib.parse.urlencode({"composeId": compose_id})
    request = urllib.request.Request(
        config["url"] + "/api/deployment.allByCompose?" + query,
        headers={"x-api-key": config["key"], "Accept": "application/json"},
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(
            request, timeout=20
        ) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Dokploy verification API returned HTTP {exc.code}"
        ) from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Dokploy verification API failed: {type(exc).__name__}"
        ) from None
    if not isinstance(result, list) or any(
        not isinstance(item, dict) for item in result
    ):
        raise ValueError(
            "Unexpected Dokploy deployment response; expected an array of records"
        )
    return result


def record_time(record):
    value = record.get("createdAt")
    if not isinstance(value, str):
        raise TypeError("Dokploy deployment is missing createdAt")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))  # noqa: FURB162 - Python 3.10 support
    if parsed.tzinfo is None:
        raise ValueError("Dokploy deployment createdAt must include a timezone")
    return parsed


def record_commit(record):
    value = record.get("description")
    match = COMMIT.fullmatch(value) if isinstance(value, str) else None
    return match[1] if match else None


def wait_for_deployments(
    plan, hive_sha, config=None, fetch=None, clock=time.monotonic, sleep=time.sleep
):
    if not SHA.fullmatch(hive_sha):
        raise ValueError("Expected full Hive commit SHA")
    services = affected_services(plan)
    if not services:
        return {}
    config = configuration(plan) if config is None else config
    fetch = (
        (lambda compose_id: fetch_deployments(config, compose_id))
        if fetch is None
        else fetch
    )
    deadline = clock() + config["timeout"]
    while True:
        verified = {}
        pending = []
        for service in services:
            records = fetch(config["ids"][service])
            if not isinstance(records, list) or any(
                not isinstance(r, dict) for r in records
            ):
                raise ValueError("Unexpected Dokploy deployment response")
            records = sorted(records, key=record_time, reverse=True)
            matching = [
                record for record in records if record_commit(record) == hive_sha
            ]
            if not matching:
                pending.append(service)
                continue
            record = records[0]
            if record_commit(record) != hive_sha:
                raise RuntimeError(
                    f"Dokploy deployment for {service} was superseded by another commit"
                )
            status = record.get("status")
            if status == "done":
                deployment_id = record.get("deploymentId")
                if not isinstance(deployment_id, str) or not deployment_id:
                    raise ValueError("Completed Dokploy deployment is missing its ID")
                if (
                    record.get("composeId", config["ids"][service])
                    != config["ids"][service]
                ):
                    raise ValueError(
                        "Dokploy deployment belongs to another Compose service"
                    )
                verified[service] = deployment_id
            elif status in ("queued", "running"):
                pending.append(service)
            else:
                raise RuntimeError(
                    f"Dokploy deployment for {service} failed or has an unknown status"
                )
        if not pending:
            return verified
        if clock() >= deadline:
            raise TimeoutError(
                "Timed out verifying exact Hive deployment for: " + ", ".join(pending)
            )
        sleep(min(10, max(0, deadline - clock())))
