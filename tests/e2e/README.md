# Manual end-to-end test launcher

`run_all_e2e.sh` is a host-specific orchestration script, not a complete portable
test suite. Its suite list points to Python scripts under `/tmp`, and its backend
path is hard-coded to the author's checkout. A clean clone does not contain all
of those scripts. Use [development checks](../../docs/development.md) for
reproducible checked-in tests and CI.

## Inspect before running

From the repository root:

```bash
bash tests/e2e/run_all_e2e.sh --list
```

The list covers REST, cross-user isolation, chat/SSE, MCP, briefing lifecycle,
ingestion, security, performance, and CLI workflows. It is the authoritative list;
counts and old suite names in previous docs may no longer apply.

Before executing, inspect each selected script, provide its expected local test
accounts and environment, and adapt the launcher's backend path to your checkout.
Run against an isolated stack: suites may create/delete data and call paid models.
The existing launcher reads backend environment files; ensure these target your
intended disposable environment.

Once those prerequisites are satisfied:

```bash
bash tests/e2e/run_all_e2e.sh --only briefing
bash tests/e2e/run_all_e2e.sh --only 'CLI browser-handoff login'
bash tests/e2e/run_all_e2e.sh
```

The backend health endpoint is `http://localhost:8000/api/health`. MCP suites need
the server at port 8001. Frontend/browser probes require their own browser/runtime
and app setup. A suite can fail because its `/tmp` script is absent; that is not
application test evidence.

## Results and maintenance

Logs are written to `/tmp/e2e_results_<timestamp>/`, one file per suite. The summary
prints failure tails. Inspect logs before retrying: authentication throttling,
provider latency, missing fixtures, and product regressions require different fixes.

New reusable suites should live in the repository with documented fixtures and
configuration. Avoid adding another undocumented `/tmp` dependency. Keep the
launcher list synchronized with the actual executable scripts.

See [retrieval evaluation](../../backend/eval/README.md) for IR quality gates and
[documentation index](../../docs/README.md) for service guides.

## Root access V2 browser and native acceptance

`e2e_root_access_v2_browser.cjs` runs the actual React interface and API/provider,
without route mocks. It creates one dedicated synthetic root. Never point it at
an existing company root. Requirements:

- Integrated V2 backend, migrations and frontend, with the central vault configured.
- Node and Playwright installed in `KIOKU_PLAYWRIGHT_DIR` (a directory containing
  `node_modules/playwright`), and Chrome available via `KIOKU_CHROME_PATH`.
- An authenticated owner Playwright storage-state JSON in `KIOKU_E2E_AUTH`, mode
  `0600`. No password, token or credential goes in command-line arguments.

```bash
export KIOKU_V2_E2E_RELEASE_READY=1
export KIOKU_V2_E2E_KEEP_FIXTURE=1
export KIOKU_PLAYWRIGHT_DIR=/tmp/kioku-live-ui-qa
export KIOKU_E2E_AUTH=/tmp/kioku-live-ui-qa/auth.json
export KIOKU_E2E_BASE=http://127.0.0.1:5178
export KIOKU_E2E_API_BASE=http://127.0.0.1:18081
node tests/e2e/e2e_root_access_v2_browser.cjs
```

Use the published HTTPS frontend for release acceptance, or an integrated local
frontend proxying the real candidate API for pre-release acceptance. The script
records which origin was used; those are different validation claims.

The first phase checks environment/resource creation, direct bundle storage,
rotation without a previous session token, per-environment region, usage recipes,
computer approval and explicit grants. It leaves a private `0600`
`cli-fixture.json` in `KIOKU_E2E_ARTIFACTS` (default
`/tmp/kioku-live-ui-qa/vault-v2-final-e2e`). That file includes a synthetic device
token, IDs/revisions, expected hashes and nonsecret region for the real native CLI
pipeline. Do not print it or upload it as a CI artifact. No raw credential values
are saved. Run native env/profile consumer, cleanup, redaction and stale-revision
checks before revoking access:

```bash
node tests/e2e/e2e_root_access_v2_browser.cjs resume
```

Resume checks stale grant approval, reapproval, UI grant/device revocation and
responsive saved-state drawers. Then run the native denial check.

Provider cleanup must precede deleting folder metadata. An authorized service
operator must find **all** provider references/write operations scoped to the
recorded synthetic root, including rotated objects, delete and verify those
objects, then delete the synthetic root. The browser intentionally cannot read
provider references. It retains metadata by default. An optional executable
`KIOKU_V2_E2E_CLEANUP_HOOK` receives `root_id` and the private fixture path and must
perform that ordered cleanup; the browser then verifies root `404`. KEEP_FIXTURE
always suppresses automatic cleanup. Remove the private device fixture after
verified cleanup. A new create run refuses to overwrite a retained fixture.

Results/checkpoints contain only metadata/status; no tracing/HAR or request-body
logging is enabled. Screenshots are allowed only after secret editors are empty.
Do not count a candidate origin as published production acceptance.
