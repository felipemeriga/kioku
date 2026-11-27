# Replaying Kioku’s memory audit

The harness executes Kioku’s original archive writer, parser, index worker, Python memory services and PostgreSQL functions from release `3636866fc7094606cc1e498ad79eaf3840d72f99`. [Protocol](../../../docs/eval/memory-quality-audit-plan.md)

The PostgreSQL bridge replaces PostgREST and the filesystem bucket replaces Supabase Storage. Public trials enter the MCP Python callable with a synthetic authorized scope. Operational controls additionally call native chat dispatch, prefetch and the MCP HTTP middleware. The benchmark trials have no model, answer judge or environment actions.

## Setup

Use a fresh PostgreSQL 16 instance with an isolated volume and a loopback-only connection. Create the database `kioku_memory_audit` with a disposable owner allowed to install extensions and create roles. Create the schema `kioku_audit_guard` in that database before running the harness. Use this instance only for the audit because initialization creates cluster-level roles and applies the archive, memory, journal and report migrations.

Store a mode-`0600` JSON configuration outside the worktree. Supply `host` as `127.0.0.1`, the loopback `port`, `dbname` as `kioku_memory_audit` and the disposable `user` and `password`. Place it in a private directory. The filesystem bucket lives in a sibling `storage/` directory and must stay paired with this database.

Run these commands from `backend/` using a Python 3.12 environment with the project’s backend dependencies. `pyarrow` is only needed to freeze the BEAM and MemoryAgentBench Parquet files.

```bash
uv sync --frozen --no-default-groups --group dev --no-install-project
uv pip install --python .venv/bin/python --only-binary :all: 'psycopg[binary]==3.2.13' 'ijson==3.4.0'
uv pip install --python .venv/bin/python --only-binary :all: 'pyarrow==23.0.1'

export PYTHON_DOTENV_DISABLED=1
.venv/bin/python -m eval.memory_audit.lab --lab "$AUDIT_LAB"
.venv/bin/python -m pytest -q eval/memory_audit/tests
```

The backend CI job runs 39 scorer, archive-integrity and live-replay contract checks with temporary dependencies. The explicit PostgreSQL, corpus download and replay commands below are the manual audit.

Keep `AUDIT_DIR` outside the checkout with owner-only permissions. Use a new output path for each run. The dataset filenames, exact revisions and SHA-256 values are in [public_data.py](public_data.py), [supplemental.py](supplemental.py) and [stateful_proxies.py](stateful_proxies.py). The protocol links to each upstream release and its terms.

## Public retrieval replay

```bash
.venv/bin/python -m eval.memory_audit.replay freeze \
  --data "$AUDIT_DIR/data" --output "$AUDIT_DIR/public-frozen"

.venv/bin/python -m eval.memory_audit.replay replay \
  --lab "$AUDIT_LAB" --frozen "$AUDIT_DIR/public-frozen" --family longmemeval_s \
  --split all --output "$AUDIT_DIR/long-s.jsonl"

.venv/bin/python -m eval.memory_audit.score_public \
  --frozen "$AUDIT_DIR/public-frozen" --replay "$AUDIT_DIR/long-s.jsonl" \
  --split all --output "$AUDIT_DIR/long-s-score.json"
```

Use `--family locomo` for the second replay. The `primary` and `holdout` subsets can be scored independently from a complete result file. The public scorer verifies dataset run identity, frozen partitions, run inventory and completion counts. Use `long_extension` to freeze the 374 disjoint LongMemEval-S histories against the initial manifest.

```bash
.venv/bin/python -m eval.memory_audit.long_extension \
  --data "$AUDIT_DIR/data/longmemeval_s_cleaned.json" \
  --initial "$AUDIT_DIR/public-frozen" --output "$AUDIT_DIR/long-extension"
```

Freeze `beam_100k` and `mab_conflict` with `supplemental freeze`. Freeze `state_train_replay` and `memoryarena_prefix` with `stateful_proxies`. Each takes `--family`, `--data` and `--output`. Reuse the replay and score commands with the corresponding family. For `mab_conflict`, use the separate `supplemental score-mab` command with `--frozen`, `--replay` and `--output` to measure answer-string availability.

Freeze `state_train_full` with the same `stateful_proxies` command for the 300-trajectory STATE training study. `state_followup run --family state_train_full` then archives all three domain scopes and runs the sealed full-request and shortened-request questions. `state_followup score` takes the sealed directory, replay file and output path. It uses the separate labels to measure exact final-call and result coverage from the search page, ten latest in the selected session and signed paired read. The source is an observed training corpus, with no environment actions or answer judging.

Use `beam_scale` with the same arguments for `beam_500k_sample`, `beam_1m_sample` and `beam_10m_sample`. It streams one released conversation at a time and seals the complete selected conversation with its original pointers. The LoCoMo caption sensitivity can be reproduced with `supplemental freeze --family locomo_captions`. Use `full_long_score` with both sealed LongMemEval-S directories and both replay files to combine evidence counts across the disjoint phases.

Keep the raw source files, frozen corpus, gold and unredacted results outside Git. The replay process needs the sealed corpus and query manifest. It can run without access to `gold.json`.

## Operational and capacity controls

```bash
.venv/bin/python -m eval.memory_audit.operational freeze \
  --frozen "$AUDIT_DIR/operations"
.venv/bin/python -m eval.memory_audit.operational replay \
  --lab "$AUDIT_LAB" --frozen "$AUDIT_DIR/operations" --result "$AUDIT_DIR/ops.json"
.venv/bin/python -m eval.memory_audit.operational score \
  --frozen "$AUDIT_DIR/operations" --result "$AUDIT_DIR/ops.json" \
  --summary "$AUDIT_DIR/ops-score.json"

.venv/bin/python -m eval.memory_audit.liveness \
  --lab "$AUDIT_LAB" --output "$AUDIT_DIR/capacity-replay-4096.jsonl" \
  --segments 64 --records-per-segment 64
```

Run capacity experiments separately from latency replays. The liveness command makes scoped `process_session` calls with dedicated database connections. It records capture, parser and memory publication stages, observed wait events and broad versus selective query timings. Its timeout requests a stop between worker calls. The PostgreSQL connection may still be completing the current bounded statement.

The supplementary check commands expose their separate inputs with `--help`. `sentinels` freezes the page-size and timestamp probes. `read_budget` freezes a source-ID sample and compares signed reads, wider windows and the next relevance page. `edge_controls` uses the seeded engineering fixture to test citations and adds fresh language and inventory-limit controls. `quiescent` repeats a fixed ten-result request after the lab workers stop. `mechanism` profiles the frozen parser predicate and candidate stages against the already-seeded liveness scopes. Use `candidate_diagnostic` after indexing both LongMemEval-S phases to count event identities before and after the frozen identifier focus. Use `temporal_sensitivity` with the same phases and the upstream source to seal question-time cutoffs and score only records eligible for each cutoff.

The output filename selects a fresh fixture namespace. For the optional `mechanism` profile, first seed the supplementary liveness scopes with these basenames and keep them in the same database:

| Output basename | `--record-shape` | `--records-per-segment` | `--conditions` |
| --- | --- | ---: | --- |
| `capacity-messages-4096.jsonl` | `messages` | 64 | `one_serial` |
| `capacity-distinct-results-4096.jsonl` | `distinct_results` | 64 | `one_serial` |
| `capacity-messages-16384.jsonl` | `messages` | 256 | `one_serial four_serial` |

Use `mechanism --inspect-search` after seeding the same 16,384-chunk scope to measure the actual nested search in place. It uses the synthetic scope’s MCP callable and logs plan shapes and filter counts with `auto_explain` on its lab connection.

The `timeout_drain` command exercises a fixed workload with connection-local lock and statement budgets. It then runs a serial worker with ordinary lab defaults against the original objects, validates every source checksum, and checks idempotency. `publication_plan` varies only the PostgreSQL plan mode on the audit worker connections. These controls use fresh namespaces and require the disposable PostgreSQL audit database.

To inspect the actual nested publication plan, first run `liveness` with `--conditions one_serial --deadline 420` on the same 64-segment duplicate workload. Pass the completed output basename to `publication_plan --inspect-completed`. The optional inspection loads PostgreSQL’s `auto_explain` module on its own lab connections, passes an empty event list to the publisher and rolls back every invocation. [PostgreSQL 16 module setup](https://www.postgresql.org/docs/16/auto-explain.html)

Close the lab connection, stop the audit database instance and discard its isolated volume and disposable credentials after the run. Keep a copy of the aggregate scores and frozen hashes to compare with later runs.

## Sealed live CLI questions

Run live probes from a checkout already connected to the authorized Kioku folder. The CLI resolves connection and scope from its current working directory. Use the isolated audit checkout as the absolute Python module path. Reuse the existing connection for the audit. The replay never needs `kioku init`, a new key, or a gold file.

```bash
cd "$KIOKU_CONNECTED_CHECKOUT"
PYTHONPATH="$KIOKU_AUDIT_CHECKOUT/backend" "$AUDIT_PYTHON" \
  -m eval.memory_audit.live_replay \
  --queries "$PRIVATE_QUERY_MANIFEST" --sha256 "$SEALED_QUERY_SHA256" \
  --cutoff-ceiling "$AUDIT_CUTOFF_UTC" --timeout-seconds 45 \
  --output "$PRIVATE_REPLAY_OUTPUT"
```

Use a new private output file, an independently recorded manifest hash and an explicit cutoff at or before the scoring window begins. Supply targets in the authorized folder. Run conservatively because the replay uses the live service. Keep the manifest, independent evidence labels and raw replay outside the checkout. The replay checks the query file and writes locators, status and timing metadata. Grade those locators against separately sealed labels after the calls finish.
