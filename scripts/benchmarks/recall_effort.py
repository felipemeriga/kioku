"""Paired production recall benchmark. All answers stay in a private output directory.

Supports explicit effort, or legacy Agentic/Deep controls on adaptive native models.
Never retries inference under a new turn ID. Resume by rerunning the same command.
"""

import argparse
import hashlib
import json
import os
import random
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx


def save(path, value):
    path = Path(path)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class Client:
    def __init__(self, config):
        self.config = config
        self.auth_lock = threading.RLock()
        self.client = httpx.Client(timeout=httpx.Timeout(660, connect=20))

    def credentials(self):
        with self.auth_lock:
            return json.loads(self.config.read_text())

    def request(self, method, path, **kwargs):
        for attempt in range(2):
            cfg = self.credentials()
            response = self.client.request(
                method,
                cfg["api_base"].rstrip("/") + path,
                headers={"Authorization": "Bearer " + cfg["access_token"]},
                **kwargs,
            )
            if response.status_code != 401 or attempt:
                response.raise_for_status()
                return response
            with self.auth_lock:
                if self.credentials()["access_token"] != cfg["access_token"]:
                    continue
                auth = self.client.get(
                    cfg["api_base"].rstrip("/") + "/api/cli/auth-config"
                )
                auth.raise_for_status()
                public = auth.json()
                refreshed = self.client.post(
                    public["supabase_url"] + "/auth/v1/token?grant_type=refresh_token",
                    headers={"apikey": public["supabase_anon_key"]},
                    json={"refresh_token": cfg["refresh_token"]},
                )
                if refreshed.status_code != 200:
                    raise RuntimeError("Benchmark authentication expired")
                session = refreshed.json()
                cfg.update(
                    access_token=session["access_token"],
                    refresh_token=session["refresh_token"],
                )
                save(self.config, cfg)
        raise RuntimeError("Authentication refresh failed")

    def stream_chat(self, body):
        # Refresh before admission; failed transport retries retain the same turn ID.
        self.request("GET", "/api/chat/models")
        cfg = self.credentials()
        began = time.monotonic()
        frames, first_event, first_text = [], None, None
        with self.client.stream(
            "POST",
            cfg["api_base"].rstrip("/") + "/api/chat",
            headers={"Authorization": "Bearer " + cfg["access_token"]},
            json=body,
        ) as response:
            response.raise_for_status()
            if "text/event-stream" not in response.headers.get("content-type", ""):
                raise ValueError("Expected SSE response")
            for line in response.iter_lines():
                if not line.startswith("data: "):
                    continue
                frame = json.loads(line[6:])
                frames.append(frame)
                elapsed = time.monotonic() - began
                if first_event is None:
                    first_event = elapsed
                if frame.get("token") and first_text is None:
                    first_text = elapsed
                if frame.get("done") or frame.get("error"):
                    break
        return frames, {
            "http_seconds": time.monotonic() - began,
            "first_event_seconds": first_event,
            "first_text_seconds": first_text,
        }


def trial(client, output, item, question, folder, model, workers=1, control="explicit"):
    path = output / (item["key"] + ".json")
    state = json.loads(path.read_text()) if path.exists() else dict(item)
    if state.get("finished"):
        return state
    if (
        state.get("question", question) != question
        or state.get("folder_id", folder) != folder
    ):
        raise ValueError("Resume scope or question changed")
    if not state.get("conversation_id"):
        state["conversation_id"] = client.request("POST", "/api/conversations").json()[
            "id"
        ]
        state["turn_id"] = str(uuid.uuid4())
        state["owner_id"] = client.credentials()["user_id"]
        state["question"] = question
        state["folder_id"] = folder
        save(path, state)
        client.request(
            "PATCH",
            "/api/conversations/" + state["conversation_id"],
            json={"title": "effort-bench-" + output.name + "-" + item["key"]},
        )
    body = {
        "conversation_id": state["conversation_id"],
        "turn_id": state["turn_id"],
        "content": question,
        "model": model,
        "mode": "agentic" if item["effort"] == "low" else "deep",
        "debug": True,
        "scope_folder_id": folder,
        "timezone": "America/Sao_Paulo",
    }
    if control == "explicit":
        body["mode"] = "agentic"
        body["reasoning_effort"] = item["effort"]
    began = time.monotonic()
    state.setdefault("workers", workers)
    state["transport_resumed"] = "started_at" in state
    state.setdefault("started_at", time.time())
    save(path, state)
    try:
        frames, transport = client.stream_chat(body)
        state["transport"] = transport
        state["frames"] = frames
        terminal = next(
            (f for f in reversed(frames) if f.get("done") or f.get("error")), {}
        )
        state["terminal"] = terminal
        state["success"] = bool(
            terminal.get("done")
            and terminal.get("message_id")
            and not terminal.get("error")
        )
        state["conversation"] = client.request(
            "GET", "/api/conversations/" + state["conversation_id"]
        ).json()
        state["artifacts"] = []
        for tool in (terminal.get("debug") or {}).get("tool_calls", []):
            if not tool.get("artifact_id") or not terminal.get("job_id"):
                continue
            chunks, offset = [], 0
            while True:
                artifact = client.request(
                    "GET",
                    f"/api/chat/jobs/{terminal['job_id']}/artifacts/{tool['artifact_id']}",
                    params={"offset": offset, "limit": 65536},
                ).json()
                chunks.append(artifact)
                offset = artifact.get("next_offset")
                if offset is None:
                    break
            state["artifacts"].append({"tool": tool, "chunks": chunks})
        usage = ((terminal.get("debug") or {}).get("execution") or {}).get(
            "usage"
        ) or {}
        state["verified_control"] = usage.get("thinking_control")
        if (
            state["success"]
            and (state["verified_control"] or {}).get("effort") != item["effort"]
        ):
            state["success"] = False
            state["control_error"] = "Effort was not verified by native usage"
        state["elapsed_seconds"] = time.monotonic() - began
        state["finished"] = True
    except (httpx.HTTPError, ValueError, KeyError, OSError) as exc:
        state["transport_error"] = type(exc).__name__
        state["elapsed_seconds"] = time.monotonic() - began
        # Leave pending for same-turn reconciliation; never silently replace a trial.
        save(path, state)
        raise RuntimeError(
            "Trial transport interrupted; rerun to reconcile the same turn"
        ) from None
    save(path, state)
    return state


def cleanup(client, output, plan):
    """Delete only exported, terminal, unchanged benchmark conversations owned by this caller."""
    counts = {"deleted": 0, "retained": 0, "already_deleted": 0}
    owner = client.credentials()["user_id"]
    for item in plan:
        path = output / (item["key"] + ".json")
        if not path.exists():
            continue
        state = json.loads(path.read_text())
        if not state.get("finished"):
            counts["retained"] += 1
            continue
        conversation = state["conversation_id"]
        try:
            saved = client.request("GET", "/api/conversations/" + conversation).json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 404:
                raise
            counts["already_deleted"] += 1
            continue
        expected = "effort-bench-" + output.name + "-" + item["key"]
        terminal = client.request("GET", "/api/chat/turns/" + state["turn_id"]).json()
        if (
            saved.get("id") != conversation
            or saved.get("user_id", owner) != owner
            or state.get("owner_id", owner) != owner
            or saved.get("title") != expected
            or terminal.get("state")
            not in {"committed", "acknowledged", "failed", "cancelled", "uncertain"}
        ):
            counts["retained"] += 1
            continue
        client.request("DELETE", "/api/conversations/" + conversation)
        state["fixture_deleted_at"] = time.time()
        save(path, state)
        counts["deleted"] += 1
    save(output / "cleanup.json", counts)
    return counts


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--repo-folder", required=True)
    p.add_argument("--limited-folder", required=True)
    p.add_argument("--repo-name", default="repository")
    p.add_argument("--session-prefix", default="")
    p.add_argument(
        "--control", choices=["explicit", "legacy_modes"], default="explicit"
    )
    p.add_argument("--model", default="claude-haiku-5-5")
    p.add_argument(
        "--config", type=Path, default=Path.home() / ".config/kioku/config.json"
    )
    p.add_argument("--questions", type=Path, required=True)
    p.add_argument("--repeat-pairs", type=int, default=6)
    p.add_argument("--limit", type=int, default=64)
    p.add_argument("--workers", type=int, choices=[1, 2], default=1)
    p.add_argument("--cleanup", action="store_true")
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(args.output, 0o700)
    questions = json.loads(args.questions.read_text())
    if (
        not isinstance(questions, list)
        or not questions
        or len(questions) > 200
        or any(not isinstance(q, dict) for q in questions)
        or not 0 <= args.repeat_pairs <= 100
    ):
        p.error("Use 1-200 questions and 0-100 repeat pairs")
    if args.limit < 1 or args.limit > 600:
        p.error("Trial limit must be between 1 and 600")
    if any(
        q.get("scope") not in {"repo", "all", "limited"}
        or not isinstance(q.get("id"), str)
        or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", q["id"])
        or not isinstance(q.get("question"), str)
        or not 1 <= len(q["question"]) <= 4000
        for q in questions
    ):
        p.error("Each question requires an id, question and repo/all/limited scope")
    question_hash = hashlib.sha256(
        json.dumps(questions, sort_keys=True).encode()
    ).hexdigest()
    plan_path = args.output / "plan.json"
    if plan_path.exists():
        plan = json.loads(plan_path.read_text())
        manifest = json.loads((args.output / "manifest.json").read_text())
        if (
            manifest["questions_sha256"] != question_hash
            or manifest["model"] != args.model
        ):
            p.error("Resume requires the same frozen questions and model")
        if manifest.get("control", "legacy_modes") != args.control:
            p.error("Resume requires the original request control strategy")
    else:
        rng = random.Random(20261109)
        order = list(range(len(questions))) + [
            round(i * len(questions) / max(1, args.repeat_pairs)) % len(questions)
            for i in range(args.repeat_pairs)
        ]
        plan = []
        for pair, index in enumerate(order):
            efforts = ["low", "high"]
            rng.shuffle(efforts)
            for effort in efforts:
                plan.append(
                    {
                        "key": f"{pair:02}-{questions[index]['id']}-{effort}",
                        "pair": pair,
                        "question_index": index,
                        "effort": effort,
                    }
                )
        save(plan_path, plan)
        save(
            args.output / "manifest.json",
            {
                "model": args.model,
                "control": args.control,
                "questions_sha256": hashlib.sha256(
                    json.dumps(questions, sort_keys=True).encode()
                ).hexdigest(),
                "controls": args.control + "; verify actual native usage",
                "question_count": len(questions),
                "trial_count": len(plan),
                "started_at": time.time(),
            },
        )
    client = Client(args.config)
    if args.cleanup:
        print(json.dumps(cleanup(client, args.output, plan)))
        return

    def run_item(item):
        q = questions[item["question_index"]]
        scope = q.get("scope")
        folder = (
            None
            if scope == "all"
            else args.limited_folder
            if scope == "limited"
            else args.repo_folder
        )
        question = q["question"].format(
            repo_name=args.repo_name, session_prefix=args.session_prefix
        )
        result = trial(
            client,
            args.output,
            item,
            question,
            folder,
            args.model,
            args.workers,
            args.control,
        )
        print(
            json.dumps(
                {
                    "key": item["key"],
                    "success": result.get("success"),
                    "seconds": round(result.get("elapsed_seconds", 0), 2),
                    "effort_verified": result.get("verified_control"),
                }
            ),
            flush=True,
        )

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(run_item, plan[: args.limit]))


if __name__ == "__main__":
    main()
