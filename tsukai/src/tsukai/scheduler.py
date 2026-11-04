"""Bounded SQL dispatcher with explicit uncertainty on worker/lease loss."""

import asyncio
import contextlib
import json
import random
import tempfile
import time
import uuid
from pathlib import Path

import httpx

from .cancellation import complete_cleanup
from .native import NativeRunner
from .protocol import JobRequest
from .store import Fenced
from .validation import NativeError


class Scheduler:
    def __init__(self, store, settings, native=None):
        self.store, self.settings = store, settings
        self.native = native or NativeRunner(settings)
        self.worker_id = str(uuid.uuid4())
        self.tasks = {}
        self.cancelling = set()
        self.draining = False
        self.auth_state = "starting"
        self.quota_until = 0
        self.db_available = False
        self.wake = asyncio.Event()
        self.loop_task = None
        self._probe_lock = asyncio.Lock()
        self._next_dependency_probe = 0
        self._dependency_backoff = 1
        self.redis_task = None

    async def start(self):
        await self.recheck_auth()
        self.loop_task = asyncio.create_task(self.loop())
        if self.settings.redis_url:
            self.redis_task = asyncio.create_task(self.redis_hints())

    async def notify(self, job_id):
        self.wake.set()
        if self.settings.redis_url:
            try:
                import redis.asyncio as redis

                client = redis.from_url(
                    self.settings.redis_url, socket_timeout=0.2, socket_connect_timeout=0.2
                )
                try:
                    await client.publish("tsukai:wake:v1", job_id)
                finally:
                    await client.aclose()
            except Exception:
                pass  # SQL polling alone is sufficient for accepted work.

    async def redis_hints(self):
        import redis.asyncio as redis

        while not self.draining:
            try:
                client = redis.from_url(self.settings.redis_url, socket_connect_timeout=1)
                try:
                    async with client.pubsub() as pubsub:
                        await pubsub.subscribe("tsukai:wake:v1")
                        while not self.draining:
                            if await pubsub.get_message(ignore_subscribe_messages=True, timeout=1):
                                self.wake.set()
                finally:
                    await client.aclose()
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(1)

    async def recheck_auth(self):
        if self._probe_lock.locked():
            return
        async with self._probe_lock:
            await self._check_auth()

    async def _check_auth(self):
        try:
            await self.store.ping()
            self.db_available = True
            await self.native.verify_version()
            if self.settings.auth_probe:
                # Admission/attempt/event accounting includes the readiness inference.
                owners = sorted(self.settings.entitled_owners)
                if not owners:
                    self.auth_state = "no_entitled_owner"
                else:
                    req = JobRequest(
                        idempotency_key="readiness-" + str(uuid.uuid4()),
                        owner_id=owners[0],
                        caller="backend",
                        operation="readiness",
                        prompt="Reply READY.",
                        model="claude-haiku-4-5-20251001",
                        max_tokens=1024,
                        max_turns=1,
                    )
                    job = await self.store.admit(req)
                    claim = await self.store.claim(self.worker_id, only_job_id=job["id"])
                    if claim:
                        await self.execute(claim)
                        result = await self.store.get(job["id"])
                        self.auth_state = (
                            "ready"
                            if result["status"] == "completed"
                            else (result["error"] or {}).get("code", "probe_failed")
                        )
                    else:
                        self.auth_state = "dependency_unavailable"
            else:
                self.auth_state = "ready"
            self._dependency_backoff = 1
        except NativeError as exc:
            self.auth_state = exc.code
        except Exception:
            self.auth_state = "dependency_unavailable"
            self.db_available = False
        self._next_dependency_probe = time.monotonic() + self._dependency_backoff
        self._dependency_backoff = min(self._dependency_backoff * 2, 60)

    async def loop(self):
        last_prune = 0
        while not self.draining:
            try:
                await self.store.expire_queued()
                await self.store.recover()
                from .lifecycle import cleanup_deletions

                await cleanup_deletions(self.store, self)
                self.db_available = True
                if (
                    self.auth_state == "dependency_unavailable"
                    and time.monotonic() >= self._next_dependency_probe
                ):
                    await self.recheck_auth()
                if time.monotonic() - last_prune > 3600:
                    await self.store.prune()
                    for spool in Path(self.settings.workspace_dir).rglob("events-*.spool"):
                        if spool.stat().st_mtime < time.time() - 30 * 86400:
                            spool.unlink(missing_ok=True)
                    last_prune = time.monotonic()
                if self.auth_state == "ready" and time.monotonic() >= self.quota_until:
                    while len(self.tasks) < 3:
                        claim = await self.store.claim(self.worker_id)
                        if claim is None:
                            break
                        task = asyncio.create_task(self.execute(claim))
                        self.tasks[claim["attempt"]["id"]] = task
                        task.add_done_callback(
                            lambda t, key=claim["attempt"]["id"]: self.tasks.pop(key, None)
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                # Pause claims on SQL loss. Existing tasks drain privately until fenced.
                self.db_available = False
            self.wake.clear()
            try:
                await asyncio.wait_for(self.wake.wait(), 0.25)
            except asyncio.TimeoutError:
                pass

    async def tool_config(self, claim, req):
        if not req.tool_allowlist:
            return None
        if not self.settings.backend_url:
            raise NativeError("tool_backend_unavailable")
        payload = {
            "job_id": claim["job"]["id"],
            "attempt_id": claim["attempt"]["id"],
            "owner_id": req.owner_id,
            "folder_ids": req.folder_ids,
            "tool_allowlist": req.tool_allowlist,
            "tool_capability_ref": req.tool_capability_ref,
            "deadline": claim["attempt"]["deadline"],
        }
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                self.settings.backend_url.rstrip("/") + "/internal/tsukai/tool-capability",
                json=payload,
                headers={"Authorization": "Bearer " + self.settings.service_token},
            )
            if response.status_code != 200:
                raise NativeError("tool_capability_denied")
            data = response.json()
        # URL is never taken from job input; backend uses its own route registry.
        expected = self.settings.backend_url.rstrip("/")
        if not data.get("mcp_url", "").startswith(expected + "/") or not data.get("capability"):
            raise NativeError("invalid_tool_backend")
        return {
            "mcpServers": {
                "kioku": {
                    "type": "http",
                    "url": data["mcp_url"],
                    "headers": {"Authorization": "Bearer " + data["capability"]},
                }
            }
        }

    def signal_cancel(self, attempt_id, task):
        if task.done() or attempt_id in self.cancelling:
            return False
        self.cancelling.add(attempt_id)
        task.cancel()
        return True

    async def execute(self, claim):
        attempt = claim["attempt"]
        req = JobRequest.model_validate(claim["job"]["request"])
        current = asyncio.current_task()
        events = asyncio.Queue()
        spool_dir = Path(claim["workspace"])
        spool_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, spool_name = tempfile.mkstemp(prefix="events-", suffix=".spool", dir=spool_dir)
        import os

        spool = os.fdopen(fd, "wb")
        spooled = 0

        async def emit(kind, data):
            nonlocal spooled
            encoded = (json.dumps({"type": kind, "data": data}) + "\n").encode()
            spooled += len(encoded)
            if spooled > self.settings.spool_bytes:
                raise NativeError("output_overflow")
            spool.write(encoded)
            spool.flush()
            events.put_nowait((kind, data))

        async def publish():
            empty = object()
            pending = empty
            while True:
                item = await events.get() if pending is empty else pending
                pending = empty
                if item is None:
                    return
                kind, data = item
                if kind == "text.delta":
                    chunks = [data["text"]]
                    size = len(chunks[0].encode())
                    until = time.monotonic() + 0.25
                    while size < 16384 and time.monotonic() < until:
                        try:
                            other = await asyncio.wait_for(events.get(), until - time.monotonic())
                        except asyncio.TimeoutError:
                            break
                        if (
                            other is None
                            or other[0] != "text.delta"
                            or size + len(other[1]["text"].encode()) > 16384
                        ):
                            pending = other
                            break
                        chunks.append(other[1]["text"])
                        size += len(other[1]["text"].encode())
                    data = {"text": "".join(chunks), "provisional": True}
                while True:
                    try:
                        await self.store.append(attempt, kind, data)
                        break
                    except Fenced:
                        raise
                    except Exception:
                        if time.time() > attempt["lease_until"]:
                            raise Fenced("event_persistence_lease_lost") from None
                        await asyncio.sleep(0.2)

        async def heartbeat():
            while True:
                await asyncio.sleep(self.settings.heartbeat_seconds)
                try:
                    cancelled = await self.store.heartbeat(attempt)
                    attempt["lease_until"] = time.time() + 30
                    if cancelled:
                        self.signal_cancel(attempt["id"], current)
                        return
                except Exception:
                    # Native cannot continue after authority becomes uncertain.
                    if time.time() >= attempt["lease_until"]:
                        self.signal_cancel(attempt["id"], current)
                        return

        heartbeat_task = asyncio.create_task(heartbeat())
        publisher = asyncio.create_task(publish())
        try:
            config = await self.tool_config(claim, req)
            remaining = attempt["deadline"] - time.time()
            if remaining <= 0:
                raise NativeError("wall_timeout")
            async with asyncio.timeout(remaining):
                result = await self.native.run(claim, req, emit, config)
            events.put_nowait(None)
            await publisher
            await self.store.finish(attempt, "completed", result=result)
        except asyncio.CancelledError:
            self.cancelling.add(attempt["id"])

            async def terminate_and_commit():
                with contextlib.suppress(Exception):
                    await self.store.heartbeat(attempt)
                await self.native.stop(attempt["id"])
                await self.store.finish(
                    attempt, "cancelled", error={"code": "cancelled", "usage_complete": False}
                )

            with contextlib.suppress(Exception):
                await complete_cleanup(terminate_and_commit(), 20)
        except TimeoutError:
            with contextlib.suppress(Exception):
                await self.store.finish(
                    attempt, "failed", error={"code": "wall_timeout", "usage_complete": False}
                )
        except NativeError as exc:
            if exc.code == "reauth_required":
                self.auth_state = "reauth_required"
            elif exc.code == "quota_limited":
                self.quota_until = time.monotonic() + 60
            with contextlib.suppress(Exception):
                if exc.retryable:
                    await asyncio.sleep(random.uniform(0.1, 0.5))
                await self.store.finish(
                    attempt,
                    "uncertain" if exc.uncertain else "failed",
                    result=exc.result,
                    error={"code": exc.code, "usage_complete": False},
                    diagnostic=exc.diagnostic,
                    retry=exc.retryable and not exc.uncertain and req.profile != "chat",
                )
        except Exception:
            await self.native.stop(attempt["id"])
            with contextlib.suppress(Exception):
                await self.store.finish(
                    attempt,
                    "uncertain",
                    error={
                        "code": "execution_uncertain",
                        "usage_complete": False,
                        "requires_explicit_recovery": True,
                    },
                )
        finally:
            heartbeat_task.cancel()
            publisher.cancel()
            for task in (heartbeat_task, publisher):
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
            spool.close()
            # Keep private uncommitted spool only after SQL loss; it is never replay truth.
            with contextlib.suppress(Exception):
                final_job = await self.store.get(attempt["job_id"])
                if final_job and final_job["status"] in {"completed", "failed", "cancelled"}:
                    Path(spool_name).unlink(missing_ok=True)
            self.cancelling.discard(attempt["id"])
            self.wake.set()

    async def cancel(self, job_id):
        await self.store.cancel(job_id)
        for attempt_id, task in list(self.tasks.items()):
            # Task ownership is local; heartbeat catches remote cancellations.
            # Cancel configuration/mint IO too, before a native process has started.
            async with self.store.engine.connect() as conn:
                from sqlalchemy import select

                from .tables import attempts

                owner = (
                    await conn.execute(select(attempts.c.job_id).where(attempts.c.id == attempt_id))
                ).scalar_one_or_none()
            if owner == job_id:
                self.signal_cancel(attempt_id, task)

    async def drain(self):
        self.draining = True
        self.wake.set()
        if self.redis_task:
            self.redis_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.redis_task
        if self.loop_task:
            await self.loop_task
        if self.tasks:
            _, pending = await asyncio.wait(
                list(self.tasks.values()), timeout=self.settings.drain_seconds
            )
            for attempt_id, task in list(self.tasks.items()):
                if task in pending:
                    self.signal_cancel(attempt_id, task)
            await asyncio.gather(*pending, return_exceptions=True)
