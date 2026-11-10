# Tsukai

Durable native Claude Code execution service, integrated into main through PR #211.
It is an optional, explicitly configured subscription execution path for chat and
verified completion/maintenance operations. The backend defaults to API execution.

## Read first

- [Protocol and wire schemas](protocol/README.md): authorization, admission, replay,
  cancellation, usage, recovery, deletion, and native process behavior.
- [Operations](../docs/operations.md): database grants, credentials, TLS, rollout,
  drain, and backend/worker configuration parity.
- [Architecture](../docs/architecture.md): engine selection and scope boundaries.
- [Design and implementation records](../docs/README.md): original plans remain
  historical decisions, not deployment status.

## Runtime

Python 3.12+, FastAPI, SQLAlchemy/asyncpg, PostgreSQL, and a pinned native CLI.
`src/tsukai/config.py` and `Dockerfile` define the pinned version. HTTP on 8788 is
private; do not expose the internal service directly to browsers.

Run one replica with persistent native state/workspaces and a dedicated restricted
PostgreSQL login. A service bearer token authenticates transport; tenant operations
also need a backend-signed scope capability. Native credentials stay in native state
or deployment environment. No automatic API fallback exists after native failure.

Authenticated model discovery uses initialization metadata, with bounded caching
and explicit stale states. Usage-credit models are not selectable. The protocol
explains static pilot allowances and dynamic model admission.

## Validation

From the repository root:

```bash
uv sync --project tsukai --frozen
uv run --project tsukai ruff check tsukai
uv run --project tsukai ruff format --check tsukai
uv run --project tsukai pytest tsukai/tests -v
```

PostgreSQL coverage needs isolated test URLs/roles; copy the fixture setup from
`.github/workflows/checks.yml`. Unit tests alone do not validate native account
access or a production deployment. Research PR #203/#205 results are contextual
experiments, not runtime acceptance evidence for this revision.

### Optional root execution capacity

`TSUKAI_ROOT_PARALLELISM` defaults to `2` and accepts only integers `1` through `4`.
It controls the global running root-job limit, checked inside the existing SQL
advisory-locked claim transaction. One additional slot remains reserved for a
metadata child. The limit of one Mihari root, owner fairness, leases and fencing
remain unchanged. Scheduler capacity is the configured root limit plus that one
reserved metadata slot.

The Hive Tsukai compose passes `${TSUKAI_ROOT_PARALLELISM:-2}` through from the
service environment. An operator can set this nonsecret variable on that Tsukai
service and redeploy it after capacity review; omitting it retains existing
behavior. Replicas sharing an execution database must use the same setting.
No repository configuration enables a higher production limit by default.
