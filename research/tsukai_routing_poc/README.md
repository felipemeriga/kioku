# Isolated Tsukai routing POC

See [RESULTS.md](RESULTS.md) before interpreting the timings. This is research scaffolding, not the production Tsukai service. Reuses `native.py` and fixture source MCP from research PR203 commit52599f7. Server measured native CLI version2.1.318.

Only synthetic prompts/data are used. Do not expose ports18781/18782 publicly. Runtime directory contains private fixture grants and native initialization logs; never commit it. Committed results contain synthetic outputs and sanitized model/timing records only.

## Run prerequisites

- A personal native Claude login on test server; no API/provider environment inherited by native subprocesses.
- Python3, Docker, and an existing container with Anthropic Python SDK and API credentials. `api_worker.py` runs through `docker exec`, so the key stays inside that container's environment. This test used `kioku-backend` only for the isolated worker; its application routes/process/configuration were untouched.
- For actual Mihari fixture smoke, a separate checkout of PR203 commit52599f7 with its fixture dependencies (`requests`, cryptography) and actual `mihari/mihari.py`.
- Playwright plus local Chrome for the browser-only proof.

No deployment secrets, OAuth token values or API keys belong in these commands.

```sh
# Server, dedicated private test directory:
mkdir -p /tmp/kioku-tsukai-routing/{scripts,runtime}
chmod 700 /tmp/kioku-tsukai-routing/runtime
# Copy these Python/HTML files into scripts using scp.
docker cp /tmp/kioku-tsukai-routing/scripts/api_worker.py kioku-backend:/tmp/tsukai-routing-api-worker.py
python3 -u /tmp/kioku-tsukai-routing/scripts/poc.py serve --runtime /tmp/kioku-tsukai-routing/runtime
```

Separate server shell:

```sh
python3 /tmp/kioku-tsukai-routing/scripts/benchmark.py --runtime /tmp/kioku-tsukai-routing/runtime
python3 /tmp/kioku-tsukai-routing/scripts/smoke.py --runtime /tmp/kioku-tsukai-routing/runtime --actual-mihari --prior-poc-root /path/to/pr203-checkout
python3 /tmp/kioku-tsukai-routing/scripts/disconnect.py /tmp/kioku-tsukai-routing/runtime
```

On Mac:

```sh
ssh -N -L 18782:127.0.0.1:18782 meriga-server
# Open http://127.0.0.1:18782 for manual streaming.
# Browser automation: install playwright in a temporary tools directory,
# copy browser.cjs there, then run with the output directory set:
POC_BROWSER_OUTPUT=/private/tmp/browser-results node browser.cjs
```

Browser script accepts `BROWSER_EXECUTABLE`; default is the standard macOS Chrome path. Stop test server and tunnel when done, confirm the isolated API worker has exited, then remove `/tmp/tsukai-routing-api-worker.py` from the API container. Never stop the production application container to clean up the POC.

## Scope checks and lint

```sh
python3 -m unittest discover -s research/tsukai_routing_poc -p 'test_*.py' -v
uvx ruff check research/tsukai_routing_poc
uvx ruff format --check research/tsukai_routing_poc
```

The completion benchmark uses native/API engine behind the same Tsukai HTTP endpoint, plus separate direct API controls and no-model routing checks. MCP emits a normal final tool result; it does not expose token streaming to its caller. Model warmup, service startup, harness scaffolding and random inference variability remain separate from HTTP routing overhead. Stateful/agentic tool cases are functional smoke tests, not part of the matched completion timing table.
