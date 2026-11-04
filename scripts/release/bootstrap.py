"""One guarded first deployment for the pre-provisioned, idle Tsukai service."""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from deployment import NoRedirect, record_commit
from release import DIGEST, git

COMPOSE_ID = "kioku-tsukai-runner-v1"
PATH = "kioku/tsukai/docker-compose.yml"
DESCRIPTION = "Private native runner; routing disabled until acceptance"
BOOTSTRAP = "felipemeriga1/kioku-tsukai:0.1.0-bootstrap"


def initial_image(hive, sha, plan, results):
    images = [image for image in plan["images"] if image["package"] == "tsukai"]
    if not images:
        return False
    before = git("show", f"{sha}^:{PATH}", cwd=hive)
    if re.findall(r"(?m)^    image: (\S+)\s*$", before) != [BOOTSTRAP]:
        return False
    result = next(item for item in results if item["package"] == "tsukai")
    image = images[0]
    if result["image"] != image["image"] or not DIGEST.fullmatch(result["digest"]):
        raise ValueError("Invalid initial Tsukai image result")
    expected = f"{image['image']}:{image['tag']}@{result['digest']}"
    after = git("show", f"{sha}:{PATH}", cwd=hive)
    if re.findall(r"(?m)^    image: (\S+)\s*$", after) != [expected]:
        raise ValueError(
            "Initial Tsukai promotion is not the validated immutable image"
        )
    return True


def request(config, path, payload=None, **query):
    url = config["url"] + "/api/" + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    req = urllib.request.Request(
        url,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={
            "x-api-key": config["key"],
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.build_opener(NoRedirect()).open(
            req, timeout=20
        ) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Dokploy bootstrap API returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Dokploy bootstrap API failed: {type(exc).__name__}"
        ) from None


def identity(compose, config):
    expected = {
        "composeId": COMPOSE_ID,
        "name": "tsukai",
        "appName": "kioku-tsukai-runner",
        "composePath": PATH,
        "sourceType": "github",
        "owner": "felipemeriga",
        "repository": "hive",
        "branch": "main",
        "serverId": None,
    }
    if config["ids"].get("tsukai") != COMPOSE_ID or not isinstance(compose, dict):
        raise ValueError("Unexpected initial Tsukai service mapping")
    if any(compose.get(key) != value for key, value in expected.items()):
        raise ValueError("Unexpected initial Tsukai service identity")


def start(hive, sha, plan, results, config, call=None):
    if not initial_image(hive, sha, plan, results):
        return False
    # Never ask Dokploy to clone a different main than the validated promotion.
    git("fetch", "origin", "main", cwd=hive)
    if git("rev-parse", "origin/main", cwd=hive) != sha:
        raise RuntimeError("Hive advanced before initial Tsukai deployment")
    call = call or (
        lambda path, payload=None, **query: request(config, path, payload, **query)
    )
    compose = call("compose.one", composeId=COMPOSE_ID)
    identity(compose, config)
    records = call("deployment.allByCompose", composeId=COMPOSE_ID)
    if not isinstance(records, list) or any(
        not isinstance(row, dict) for row in records
    ):
        raise ValueError("Unexpected initial Tsukai deployment history")
    claim = DESCRIPTION + "; CI bootstrap requested: " + sha
    complete = DESCRIPTION + "; CI bootstrap completed: " + sha
    if compose.get("description") == complete:
        if not any(
            record_commit(row) == sha and row.get("status") == "done" for row in records
        ):
            raise RuntimeError(
                "Initial Tsukai completion has no exact deployment proof"
            )
        return False  # Never re-enable a service an operator subsequently disabled.
    if compose.get("description") == claim:
        # A lost POST response may precede the asynchronous deployment record.
        # Reconcile through the normal bounded verifier; never submit it twice.
        return True
    if (
        compose.get("description") != DESCRIPTION
        or compose.get("autoDeploy") is not False
        or compose.get("composeStatus") != "idle"
        or records
    ):
        raise RuntimeError("Tsukai is not an unused bootstrap service")
    containers = call(
        "docker.getContainersByAppNameMatch",
        appName=compose["appName"],
        appType="docker-compose",
    )
    if containers != []:
        raise RuntimeError("Initial Tsukai service already has containers")
    # Persist an at-most-once claim BEFORE the asynchronous queue submission.
    # If either response is lost, a rerun waits/fails closed rather than redeploying.
    call("compose.update", {"composeId": COMPOSE_ID, "description": claim})
    call(
        "compose.deploy",
        {"composeId": COMPOSE_ID, "title": "CI initial Tsukai deployment"},
    )
    # Do not supply a commit description: Dokploy must record the actual cloned Git SHA.
    return True


def finish(sha, config, proof, call=None):
    if "tsukai" not in proof:
        raise RuntimeError("Initial Tsukai deployment was not verified")
    call = call or (
        lambda path, payload=None, **query: request(config, path, payload, **query)
    )
    compose = call("compose.one", composeId=COMPOSE_ID)
    identity(compose, config)
    claim = DESCRIPTION + "; CI bootstrap requested: " + sha
    if compose.get("description") != claim or compose.get("autoDeploy") is not False:
        raise RuntimeError("Initial Tsukai bootstrap claim changed")
    call(
        "compose.update",
        {
            "composeId": COMPOSE_ID,
            "autoDeploy": True,
            "description": DESCRIPTION + "; CI bootstrap completed: " + sha,
        },
    )
