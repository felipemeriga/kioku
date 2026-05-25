# Eval harness

Runs the agentic-rag retrieval pipeline against a fixture corpus + golden set
and computes deterministic IR metrics (Recall@k, MRR, nDCG) plus RAGAS
quality metrics. Compares aggregates to `eval/baseline.json`; CI fails on IR
regressions, warns on RAGAS regressions.

## One-shot local run

From the project root:

```bash
./backend/eval/run_local.sh              # just run, write report
./backend/eval/run_local.sh --gate       # also assert against baseline.json
./backend/eval/run_local.sh --capture    # accept this run as the new baseline
```

The script:
- starts the local Supabase stack if needed (`supabase start`)
- applies `backend/db/schema.sql` + `backend/db/local_setup.sql` (idempotent)
- truncates the eval user's documents so dedup doesn't skip re-ingest
- exports local `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` (NOT prod — there is a
  safety guard in the runner that refuses non-local URLs unless
  `EVAL_ALLOW_REMOTE=1`)
- runs `python -m eval.runner`

Reports land in `backend/eval/eval-results/<timestamp>.json` (and `latest.json`).
The `eval-results/` dir is gitignored.

## When to recapture the baseline

Run `./backend/eval/run_local.sh --capture` only when you've *intentionally*
improved retrieval quality and want to lock in the new floor. Commit the updated
`backend/eval/baseline.json` as part of the PR that introduced the improvement.

## When the schema changes

Re-dump from prod and re-clean:

```bash
supabase db dump --schema public --file backend/db/schema.sql
python3 backend/db/clean_schema.py
```

Then re-run the eval against the new schema. If any golden-set `relevant_chunk_ids`
changed (chunker config drifted, file content was rewritten), the runner will
silently score those as misses — `python -m eval.label_helper` will print the
current chunk IDs so you can update `tests/fixtures/golden_set.yaml`.

## Files

- `runner.py` — main entry point; ingests fixtures, scores per question, writes report
- `ir_metrics.py` — deterministic Recall@k / MRR / nDCG (the CI-gated metrics)
- `update_baseline.py` — turns the latest report into `baseline.json`
- `label_helper.py` — prints stable `sha256:...:chunk_N` IDs from the fixture corpus
- `baseline.json` — current accepted aggregate; PRs must not regress IR beyond tolerance
- `run_local.sh` — the one-shot script wrapping all of the above
