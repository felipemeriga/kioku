# Eval harness

Runs the agentic-rag retrieval pipeline against a fixture corpus + golden set
and computes deterministic IR metrics (Recall@k, MRR, nDCG). CI fails on
regressions. RAGAS quality metrics (faithfulness, answer_relevancy,
context_precision, context_recall) are available behind `--ragas` for occasional
diagnostic runs but are NOT part of the default gate — they're slow and
judge-model-dependent.

## One-shot local run

From the project root:

```bash
./backend/eval/run_local.sh              # IR-only full eval (~3-5 min)
./backend/eval/run_local.sh --quick      # IR-only, 9-question subset (~1 min)
./backend/eval/run_local.sh --ragas      # add RAGAS metrics (slow, can be hours)
./backend/eval/run_local.sh --gate       # also assert against baseline.json
./backend/eval/run_local.sh --capture    # write baseline.json from this run
```

Flags compose: `--quick --ragas`, `--gate --capture`, etc.

`--quick` runs one curated question per (difficulty × retrieval_type) cell —
9 questions total, full coverage of the matrix. Use for fast iteration cycles.

`--ragas` runs RAGAS metrics in addition to IR. Each metric makes many LLM
judge calls per question, scaling with answer richness. Expect tens of minutes
to hours depending on N. Use only for milestone diagnosis, not per-PR.

The script:
- starts the local Supabase stack if needed (`supabase start`)
- applies `backend/db/schema.sql` + `backend/db/local_setup.sql` (idempotent)
- truncates the eval user's documents so dedup doesn't skip re-ingest
- disables LangSmith tracing (eval is synthetic; tracing pollutes prod project)
- exports local `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` — the runner's prod-safety
  guard refuses non-local URLs unless `EVAL_ALLOW_REMOTE=1`
- runs `python -m eval.runner`

Reports land in `backend/eval/eval-results/<timestamp>.json` (and `latest.json`).
The `eval-results/` dir is gitignored.

## When to recapture the baseline

Run `./backend/eval/run_local.sh --capture` only when you've *intentionally*
improved retrieval quality and want to lock in the new floor. Commit the updated
`backend/eval/baseline.json` as part of the PR that introduced the improvement.

If `--ragas` was used, the captured baseline will include RAGAS thresholds.
Default (IR-only) captures only IR thresholds.

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

## Diagnosing failures

`python -m eval.inspect_eval --metric mrr` (or any IR metric) prints the
worst-N questions, their expected vs retrieved chunk IDs, and the agent's
answer if `--ragas` was used in the run that produced the report.

## Files

- `runner.py` — main entry point; ingests fixtures, scores per question, writes report
- `ir_metrics.py` — deterministic Recall@k / MRR / nDCG (the CI-gated metrics)
- `update_baseline.py` — turns the latest report into `baseline.json`
- `label_helper.py` — prints stable `sha256:...:chunk_N` IDs from the fixture corpus
- `inspect_eval.py` — diagnostic helper, prints worst-N questions by any metric
- `baseline.json` — current accepted aggregate; PRs must not regress beyond tolerance
- `run_local.sh` — the one-shot script wrapping all of the above
