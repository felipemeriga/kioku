# Mihari

Cloud repository poller and knowledge-maintenance service. It checks registered
repositories for principal-branch changes, updates code/graph indexes, and
refreshes repository briefings, documentation, and learnings.

`mihari.py` is the entry point. Build from the repository root:

```bash
docker buildx build --platform linux/amd64 -f mihari/Dockerfile -t kioku-mihari .
```

Use `deploy/hive/kioku/mihari/` and `deploy/hive/env.kioku.example` for deployment.
Preserve the repository data mount and KMS/encryption credentials. Current settings
use `MIHARI_DATA`, `MIHARI_TRIGGER_TOKEN`, `MIHARI_TRIGGER_PORT`, `MIHARI_SCHEDULE`,
and backend `MIHARI_URL`. Legacy watcher aliases support rolling upgrades;
backend/CLI integrations use `/api/mihari`.

Native maintenance requires explicit `TSUKAI_MIHARI_NATIVE` enablement and
backend-prepared, signed requests. Mihari submits directly to Tsukai; domain
publication and result acknowledgement remain backend responsibilities. Keep
source revision freshness and publication receipts distinct from runner completion.

Run backend/Mihari Ruff checks from [development](../docs/development.md).
See [operations](../docs/operations.md) for rollout and
[architecture](../docs/architecture.md) for the service boundaries.
