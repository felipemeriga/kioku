"""Authenticated discovery uses initialization controls only, never a paid query."""

import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest

from tsukai.config import Settings
from tsukai.models import CatalogUnavailable, ModelCatalog


def info():
    return {
        "models": [
            {
                "value": "sonnet",
                "resolvedModel": "claude-sonnet-5-5",
                "displayName": "Sonnet",
                "description": "Sonnet 5.5",
                "supportsEffort": True,
                "supportedEffortLevels": ["low", "high"],
                "supportsAdaptiveThinking": True,
            },
            {
                "value": "fable",
                "resolvedModel": "claude-fable-5-1",
                "displayName": "Fable",
                "description": "Fable 5.1 · Requires usage credits",
            },
        ],
        "account": {
            "email": "must-not-escape@example.com",
            "organization": "private",
            "subscriptionType": "max",
            "tokenSource": "CLAUDE_CODE_OAUTH_TOKEN",
        },
    }


async def test_cache_singleflight_credit_flag_and_private_account_redaction():
    catalog = ModelCatalog(Settings())
    catalog.discover = AsyncMock(return_value=info())
    results = await asyncio.gather(*(catalog.get() for _ in range(5)))
    assert catalog.discover.await_count == 1
    result = results[0]
    assert result["models"][0]["supportsAdaptiveThinking"] is True
    assert result["models"][0]["selectable"] is True
    assert result["models"][1]["requires_usage_credits"] is True
    assert result["models"][1]["selectable"] is False
    assert "must-not-escape" not in json.dumps(result) and "organization" not in result["account"]
    results[0]["models"].clear()
    assert len((await catalog.get())["models"]) == 2
    catalog._fetched = time.monotonic() - 1000
    catalog.discover.side_effect = RuntimeError("private credentials")
    stale = await catalog.get()
    assert stale["stale"] is True and "private credentials" not in json.dumps(stale)


async def test_failed_first_discovery_returns_sanitized_unavailable():
    catalog = ModelCatalog(Settings())
    catalog.discover = AsyncMock(side_effect=RuntimeError("secret"))
    with pytest.raises(CatalogUnavailable) as error:
        await catalog.get()
    assert "secret" not in str(error.value)


async def test_actual_child_receives_only_initialize_and_has_tools_hooks_and_persistence_disabled(
    tmp_path, monkeypatch
):
    fixture = tmp_path / "catalog-cli"
    evidence = tmp_path / "observed.json"
    fixture.write_text("""#!/usr/bin/env python3
import json,sys,os
if "--version" in sys.argv:
 print("2.1.318 (Claude Code)");raise SystemExit
line=sys.stdin.readline(); record=json.loads(line)
if record.get('type') != 'control_request':raise SystemExit(23)
if record['request'].get('subtype') != 'initialize':raise SystemExit(24)
with open(os.environ['CATALOG_TEST_EVIDENCE'],'w') as f:
 json.dump({'input':record,'argv':sys.argv[1:]},f)
print(json.dumps({'type':'control_response','response':{'request_id':record['request_id'],'subtype':'success','response':{'models':[],'account':{}}}}),flush=True)
sys.stdin.read()
""")
    fixture.chmod(0o700)
    catalog = ModelCatalog(Settings(native_bin=str(fixture), kill_grace_seconds=0.01))
    # Instrument only the disposable fake child; production environment remains whitelisted.
    from tsukai.native import NativeRunner

    original = NativeRunner.environment
    monkeypatch.setattr(
        NativeRunner,
        "environment",
        lambda self, req: {**original(self, req), "CATALOG_TEST_EVIDENCE": str(evidence)},
    )
    assert await catalog.discover() == {"models": [], "account": {}}
    observed = json.loads(evidence.read_text())
    assert observed["input"]["type"] == "control_request"
    assert "message" not in observed["input"]
    argv = observed["argv"]
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert json.loads(argv[argv.index("--settings") + 1])["disableAllHooks"] is True
    assert "--no-session-persistence" in argv
    assert json.loads(argv[argv.index("--mcp-config") + 1]) == {"mcpServers": {}}
    assert "--model" not in argv


def test_new_model_native_cost_and_identity_are_preserved_without_legacy_price_fallback():
    from tsukai.usage import usage_record

    models = {
        "claude-opus-5-5": {
            "inputTokens": 11,
            "outputTokens": 7,
            "cacheReadInputTokens": 0,
            "cacheCreationInputTokens": 0,
            "costUSD": 0.123,
            "canonicalModel": "claude-opus-5-5",
        }
    }
    result = usage_record(
        {"modelUsage": models, "total_cost_usd": 0.123},
        {"counter_segment": "segment", "resume": False},
    )
    assert result["model_usage"] == models
    assert result["list_equivalent_usd"] == 0.123
    assert result["billing_mode"] == "subscription" and result["complete"] is True


async def test_concurrent_cold_failure_has_one_probe_and_short_negative_cache():
    catalog = ModelCatalog(Settings())
    catalog.discover = AsyncMock(side_effect=RuntimeError("secret"))
    results = await asyncio.gather(*(catalog.get() for _ in range(8)), return_exceptions=True)
    assert catalog.discover.await_count == 1
    assert all(isinstance(result, CatalogUnavailable) for result in results)
    with pytest.raises(CatalogUnavailable):
        await catalog.get()
    assert catalog.discover.await_count == 1
    catalog._retry_after = 0
    catalog.discover.side_effect = None
    catalog.discover.return_value = info()
    assert (await catalog.get())["stale"] is False
    assert catalog.discover.await_count == 2
