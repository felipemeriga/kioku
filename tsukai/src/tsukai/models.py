"""Authenticated CLI initialization metadata. No user input or generation is sent."""

import asyncio
import copy
import json
import re
import tempfile
import time
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from .cancellation import complete_cleanup
from .native import NativeRunner

MODEL_FIELDS = (
    "value",
    "resolvedModel",
    "displayName",
    "description",
    "supportsEffort",
    "supportedEffortLevels",
    "supportsAdaptiveThinking",
    "supportsFastMode",
    "supportsAutoMode",
)


class CatalogUnavailable(Exception):
    pass


class ModelCatalog:
    def __init__(self, settings):
        self.settings = settings
        self._cached = None
        self._fetched = 0
        self._retry_after = 0
        self._lock = asyncio.Lock()

    def _unavailable(self):
        if self._cached:
            return {**copy.deepcopy(self._cached), "stale": True}
        raise CatalogUnavailable()

    async def get(self):
        if time.monotonic() < self._retry_after:
            return self._unavailable()
        if self._cached and time.monotonic() - self._fetched < 900:
            return copy.deepcopy(self._cached)
        async with self._lock:
            if time.monotonic() < self._retry_after:
                return self._unavailable()
            if self._cached and time.monotonic() - self._fetched < 900:
                return copy.deepcopy(self._cached)
            try:
                info = await self.discover()
                rows = []
                for model in info.get("models", []):
                    if not isinstance(model, dict) or not all(
                        isinstance(model.get(key), str)
                        for key in ("value", "resolvedModel", "displayName", "description")
                    ):
                        continue
                    row = {key: model[key] for key in MODEL_FIELDS if key in model}
                    requires_credits = bool(
                        re.search(r"requires? usage credits?", row["description"], re.IGNORECASE)
                    )
                    row.update(
                        requires_usage_credits=requires_credits, selectable=not requires_credits
                    )
                    rows.append(row)
                if not rows:
                    raise CatalogUnavailable()
                self._cached = {
                    "schema_version": 1,
                    "cli_version": self.settings.native_version,
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                    "stale": False,
                    "models": rows,
                    "account": {
                        key: info["account"][key]
                        for key in ("subscriptionType", "tokenSource", "apiProvider")
                        if isinstance(info.get("account", {}).get(key), str)
                    },
                }
                self._fetched = time.monotonic()
                self._retry_after = 0
                return copy.deepcopy(self._cached)
            except Exception:
                self._retry_after = time.monotonic() + 30
                return self._unavailable()

    async def discover(self):
        # The whole metadata probe has one deadline; cancellation-safe reaping
        # remains separately bounded by kill_grace_seconds * 2 + 2.
        async with asyncio.timeout(30):
            return await self._discover()

    async def _discover(self):
        runner = NativeRunner(self.settings)
        await runner.verify_version()
        key = str(uuid.uuid4())
        request_id = str(uuid.uuid4())
        proc = None
        stderr_task = None
        with tempfile.TemporaryDirectory(prefix="kioku-model-catalog-") as cwd:
            try:
                proc = await asyncio.create_subprocess_exec(
                    self.settings.native_bin,
                    "-p",
                    "--input-format",
                    "stream-json",
                    "--output-format",
                    "stream-json",
                    "--verbose",
                    "--tools",
                    "",
                    "--strict-mcp-config",
                    "--mcp-config",
                    '{"mcpServers":{}}',
                    "--setting-sources",
                    "",
                    "--settings",
                    json.dumps(
                        {
                            "disableAllHooks": True,
                            "claudeMdExcludes": [
                                "**/CLAUDE.md",
                                "**/AGENTS.md",
                                "**/.claude/rules/**",
                            ],
                        }
                    ),
                    "--permission-mode",
                    "dontAsk",
                    "--no-session-persistence",
                    "--disable-slash-commands",
                    "--no-chrome",
                    cwd=cwd,
                    env=runner.environment(
                        SimpleNamespace(
                            model="claude-haiku-4-5-20251001", max_tokens=1024, thinking_tokens=0
                        )
                    ),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                    limit=2 * 1024 * 1024,
                )
                runner.processes[key] = proc

                async def discard_stderr():
                    count = 0
                    while chunk := await proc.stderr.read(8192):
                        count += len(chunk)
                        if count > 65536:
                            raise CatalogUnavailable()

                stderr_task = asyncio.create_task(discard_stderr())
                # This is the SDK initialize control request, not a user message.
                proc.stdin.write(
                    (
                        json.dumps(
                            {
                                "type": "control_request",
                                "request_id": request_id,
                                "request": {
                                    "subtype": "initialize",
                                    "hooks": {},
                                    "sdkMcpServers": [],
                                },
                            }
                        )
                        + "\n"
                    ).encode()
                )
                await proc.stdin.drain()
                async with asyncio.timeout(20):
                    count = 0
                    while line := await proc.stdout.readline():
                        count += len(line)
                        if count > 2 * 1024 * 1024:
                            raise CatalogUnavailable()
                        event = json.loads(line)
                        response = event.get("response", {})
                        if (
                            event.get("type") == "control_response"
                            and response.get("request_id") == request_id
                        ):
                            if response.get("subtype") != "success" or not isinstance(
                                response.get("response"), dict
                            ):
                                raise CatalogUnavailable()
                            return response["response"]
                    raise CatalogUnavailable()
            finally:

                async def cleanup():
                    if proc:
                        if proc.stdin:
                            proc.stdin.close()
                        await runner.stop(key)
                    if stderr_task:
                        stderr_task.cancel()
                        await asyncio.gather(stderr_task, return_exceptions=True)

                await complete_cleanup(cleanup(), self.settings.kill_grace_seconds * 2 + 2)
