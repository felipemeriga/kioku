# c360 temporal graph experiment

This is a manual, isolated experiment. It does not change Kioku retrieval, register
CI jobs, or publish private source data. A real Neo4j Community server runs in a
dedicated Docker Compose project. The image is pinned by digest.

## Questions being tested

- Can a related past attempt be found when the question uses different wording?
- Can the answer distinguish a proposal, a reported experiment, a measured result,
  a merge, a deployment, and a later reversal?
- Does every traversal obey its historical cutoff, including its supporting
  evidence, rather than allowing a future edge to rewrite an earlier state?
- Are environment, host, version, workload, and unresolved attribution retained?
- Does graph traversal improve over both journal-first search and the **same
  extracted facts** searched without a graph?

Import success, a seeded graph query, and retrieval accuracy are different results.
Extraction quality and answer quality must be evaluated separately. Missing archive
coverage is not evidence that an attempt never happened. A mutable session summary
does not establish what was known at an earlier capture time.

## Private artifacts

Keep inventories, originals, questions, gold annotations, graph authentication,
and detailed receipts outside this repository in a directory with mode `0700`.
Files containing source data use `0600`. Do not pass service credentials on command
lines, store them in the experiment, or create a production conversation for a test.

The authorized export starts with a frozen, user/folder-scoped Supabase inventory.
`export_archive.py` reads that inventory and downloads only its committed segments
through an existing authorized SSH host. The backend's credentials remain inside
its process environment. Every downloaded object is checked against its original
byte length and SHA-256, including legacy gzip storage. A receipt records missing
or corrupt objects. The export performs no database or Storage writes.

```bash
python3 export_archive.py --objects /private/objects.json \
  --user-id USER_UUID --folder-id FOLDER_UUID --host AUTHORIZED_SSH_HOST \
  --output /private/originals.tar.gz
```

Generate a private env file with `NEO4J_AUTH=neo4j/<random-local-password>`, then:

```bash
docker compose --project-name kioku-c360-temporal-poc \
  --env-file /private/neo4j.env -f compose.yaml up -d
```

Only loopback ports `17474` and `17687` are published. The graph is disposable and
uses its own volume; production Supabase remains read-only. Stop with the same
Compose project and file. Do not use `--remove-orphans` or remove unrelated volumes.

## Evaluation contract

Freeze corpus hashes and a cutoff before extraction or evaluation. Separate the
question manifest from answer annotations; retrieval callers must not load gold.
Report development cases separately from questions held out before tuning. Compare
systems using identical scope, evidence, cutoffs, and result budgets. Include an
equal-facts nongraph baseline so improvements in extraction are not attributed to
the database engine. Preserve failures and abstentions in the denominator.

Measure temporal leakage, stale recommendations, unsupported status transitions,
provenance validity, retrieval coverage, answer completeness, abstention, and cold
and warm latency separately. Include restart, repeat-import, and cutoff boundary
checks. Original evidence remains authoritative; journal snapshots are discovery
hints with potentially revised summaries.

At least four hours of active investigation and testing are required for this
experiment. Elapsed waiting for downloads alone does not satisfy that requirement.

## Interim findings (2026-11-28; experiment remains active)

The frozen corpus contains 870 journal entries, 43 archived sessions, 4,803
verified original segments and 302,607 projected native records. All records were
compared against their SQLite projection and exact archive locators: zero field,
locator or command/result-pairing discrepancies. Twenty journal objects were
separately downloaded and hash-verified; all 870 indexed entries matched their
source objects. Publication timestamps now gate journal discovery, independently
of original-record timestamps. Eight journal sessions have no archived originals
in the authorized corpus; their summaries cannot become verified original facts.

The semantic overlay currently contains **58 manually reviewed claims**, not an
automatically extracted representation of the full corpus. Each status retains
its evidence authority. A report of a merge is not a deployment; a replay result
is not a live result; a correction is known only after its own source timestamp.

An initial diagnostic evaluated 40 reviewed evidence items across 11 positive
questions, plus three journal-only and two unsupported questions. Graph traversal
and the equal-facts SQLite baseline each covered **39/40 items (10/11 complete
questions)** at a budget of eight claims. The missing item was an older isolated
memory-budget experiment crowded out by newer results. **No graph advantage has
been demonstrated by this diagnostic.**

These are post-inspection, root-reviewed evidence-coverage measurements, **not
blind answer accuracy**. Despite the original manifest's `holdout` labels, its
questions were subsequently seen during curation. The journal-first SQLite proxy
covered 5/40 exact reviewed quotations, but does not implement production Voyage
reranking or adaptive follow-up searches. That number must not be presented as
Kioku production quality or as a fair graph-versus-production accuracy comparison.
A separate read-only production replay is being collected.

The corrected 16-question replay completed 48 method calls without execution
errors. A further 232 real-claim boundary probes passed: each of the 58 claims was
queried one microsecond before and exactly at its knowledge boundary in both
stores. Those probes use a larger result budget to isolate temporal gating from
ranking; they do not measure natural-language answer quality. Earlier failed
replay receipts remain retained privately.

The four-hour provenance/cutoff soak is **still running**, against its original
frozen query revision. It is not four hours of validation of later query changes.
Restart durability, broader discovery without curated claims and final measured
latency/reporting remain pending. Production retrieval is unchanged.

### Additional reproducible checks

After `corpus.py`, `graph.py`, `attest_journals.py` and `facts.py` have created and
verified the private artifacts, run the local suite and real-source probes:

```bash
python -m unittest discover -s scripts/temporal_graph_poc -p 'test_*.py'
python scripts/temporal_graph_poc/temporal_replay.py \
  --corpus /private/corpus.sqlite --revision FACTS_REVISION \
  --env-file /private/neo4j.env --output /private/temporal-boundaries.json
python scripts/temporal_graph_poc/score_evidence.py \
  --gold /private/reviewed-evidence-gold.json \
  --replay /private/replay.jsonl --corpus /private/corpus.sqlite \
  --output /private/evidence-coverage.json
```

The scorer reads gold only after retrieval. Preserve the gold and replay hashes,
including unsuccessful trials. Private receipts, source quotations and credentials
must remain outside git.

### Further controls collected before soak completion

- Five repeated passes completed **240 local method calls**, with zero execution
  errors and unchanged curated evidence coverage. Median component latency was
  3.229 ms for equal-facts SQLite, 14.767 ms for Neo4j, and 110.257 ms for the
  frozen lexical journal proxy. These are warm-process local component timings,
  not production request latency or model generation time.
- An automatic, question-independent identifier projection generated 54,937
  co-mentions over 1,641 identifiers. SQLite adjacency and actual Neo4j traversal
  returned identical candidates for all 16 questions. Replacing four lexical
  results with neighboring messages reduced selected-anchor coverage from 5/40
  to 3/40. Co-mention expansion is not a proven improvement.
- Eight exploratory paraphrases missed their expected concept with the lexical
  concept resolver. Reranking bare concept names was also insufficient. A separate
  baseline embedded all 870 frozen journal bodies using Voyage-3, retaining
  publication cutoffs, and followed their exact original-window pointers.
  It reads no curated claims or gold to retrieve candidates. Original transcripts
  are **not** embedded, and neither production indexes nor retrieval are modified.
- Semantic journal discovery reached relevant histories for several paraphrases
  missed by lexical entry selection, but broad questions remained ambiguous.
  This is a qualitative discovery observation, **not** measured answer accuracy.
  The exact-anchor diagnostic stayed low (4/40) for its eight-record window budget;
  different valid supporting events can also miss the selected quotation metric.
  Better topic discovery must not be reported as complete original-evidence recall.
- For all 24 vector-window questions, graph and SQL expansion returned identical
  selected originals. The initial graph window lookup was missing a composite
  stream/sequence index and took roughly 1–2 seconds. After indexing, the eight
  paraphrase cases had a 17.506 ms median graph expansion time versus 11.150 ms
  for SQLite. These timings exclude **precomputed query embeddings** and therefore
  cannot be used as live semantic-search end-to-end latency.
- The production read-only replay completed 14/16 cases on its first pass. Two
  encountered timeouts; retries sometimes passed. A later staged repeat reproduced
  `evidence_query_timeout` while searching a selected session's originals, after
  journal discovery had succeeded. This is a separate production finding, not a
  graph failure, and has not been repaired by this isolated experiment.

The evidence still supports **no demonstrated benefit from adopting a graph
store in production**. Temporal gating and well-grounded facts help both stores.
The long-duration run, durability checks and final artifact audit remain pending.

### Specific-attempt follow-up

A further eight exploratory questions exercised common scope mistakes: an
isolated SDK budget versus the full player, a corrected drift forecast, an old
installed binary versus a later patch, cloud versus replay measurements, merge
versus Windows rollout, and a queued versus completed deployment. Initially the
512MiB question missed its named older experiment because seeds were chosen by
recency alone. Literal word-boundary relevance now precedes recency in **both**
stores; no source facts were added or rewritten for this change. All eight cases
then retrieved their selected scope-disambiguating anchors. This is a targeted,
post-inspection regression result, not an independent accuracy benchmark.

The original 16 questions still cover 39/40 selected anchors in both fact stores.
Their broad memory question now misses different anchors: SQLite omits the
combined-controls experiment; Neo4j omits the older isolated SDK comparison.
Equal aggregate scores do not mean identical answers or complete coverage.
The 232 exact knowledge-boundary checks passed again after the ranking change.
