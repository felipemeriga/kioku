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
