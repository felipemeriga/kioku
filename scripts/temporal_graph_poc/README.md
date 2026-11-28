# c360 temporal graph experiment

This isolated POC tests whether a real graph database improves “have we tried
something similar?” recall over c360-lead journals and original conversations.
It uses Neo4j Community 5.26.33, with a digest-pinned Docker image, a dedicated
volume/network, loopback ports, and a 2 CPU / 2 GiB container limit. Production
retrieval is unchanged. No private evaluation runs in CI.

**Current recommendation: do not add a production graph database on the strength
of these results.** Both stores preserve the tested temporal contracts when given
the same evidence model. The graph has not demonstrated better evidence coverage;
extraction omissions and discovery/ranking remain material limitations. This is
not a certification of generated-answer accuracy or current production state.

## Data and provenance

The read-only export freezes the authorized user/folder scope before downloading.
Credentials remain in the existing backend environment. Inventories, source text,
questions, annotations, model inputs, graph authentication and detailed receipts
stay outside git in an owner-only private directory.

| Frozen source | Coverage |
| --- | --- |
| Journal entries | 870 across 20 verified daily Markdown objects |
| Archived sessions | 43, including recorded parent/child links and source gaps |
| Original segments | 4,803 inventory segments; 4,291 unique byte contents |
| Native records projected | 302,607; 131,215 displayable |
| Supporting attachment | One 26,722-byte object, verified but not interpreted |
| Latest reviewed overlay | 59 claims, 59 original supports, 19 typed relationships |

Every segment's stored length and SHA-256 were checked. A separate full cache
rehash verified 470,549,455 bytes. All projected record fields, archive locators and
command/result links were compared with the frozen SQLite projection. Journal
source objects were independently verified against all 870 indexed entries.

Coverage is incomplete: eight journal sessions (59 entries) have no archived
originals anywhere in the authorized owner inventory. Other sessions report
upstream truncation or unreadable sources. Opaque native payloads are retained,
not decoded into invented messages. Missing evidence never proves “never tried.”

The semantic overlay is **manually reviewed and deliberately small**, not an
automatic extraction of the full corpus. It contains 57 assistant reports, one
tool observation and one user correction. A faithful assistant report is not
independent proof that the reported world state was true.

## Temporal and status contract

Claims retain their original role, authority, host, environment, mode, workload,
version and status where supported. Proposals, reported experiments, measured
outputs, merges and deployments remain distinct. Every claim carries exact source
quotations and byte locators. Current validity remains unestablished by the archive.

`known_at` is no earlier than all required supporting originals; `valid_at` is
separate. Every traversed node, relationship and supporting proof must satisfy the
query cutoff. Later corrections do not rewrite what was known earlier. A newer
measurement on a different host or workload does not invalidate an older result.
Journals are revisable discovery hints: both capture and publication timestamps
must satisfy the cutoff. Unavailable older journal revisions are disclosed.

Relationships distinguish `SUPERSEDES`, `RETESTS`, `CONTRADICTS`, `EXPLAINS`,
`RESOLVES` and `EXTENDS`. They require reviewed evidence; co-mention alone cannot
establish causality or resolution. Each extraction revision has an immutable
namespace, so ongoing trials do not silently change when extraction is corrected.

Concrete cases include Final shutdown ownership versus deployment, CGID grouping
versus unproven SSE failure attribution, isolated memory-budget experiments versus
full-player runs, audio offset versus drift, replay versus live telemetry, merged
code versus Windows rollout, and later recordings versus earlier test results.

## Methods and evaluation limits

The 16-question manifest contains 11 original-backed positive cases, three
journal-only cases and two unsupported controls. Eight paraphrases, eight specific
attempt questions and two unextracted-source challenges add exploratory coverage.
These are 34 questions based on real work and negative controls, **not an
independently blind benchmark**. The original `holdout` labels do not change that:
the questions were seen during curation. Retrieval callers do not load gold;
selected-anchor scoring runs afterward.

| Method | What it tests |
| --- | --- |
| Journal-first SQLite proxy | Lexical journal discovery, then originals in selected sessions; no production reranker or adaptive agent loop |
| Equal-facts SQLite | The same reviewed claims, evidence and budget without a graph server |
| Neo4j facts | Reviewed temporal relations and bounded traversal over that same overlay |
| Automatic identifier adjacency | Question-independent co-mentions; graph and SQL adjacency controls |
| Journal vectors plus original windows | Voyage-3 embeddings of all 870 journals, then exact source-window expansion in SQL or graph |
| Raw-original graph search | Whether omitted details remain accessible in the full original-text projection |
| Read-only production replay | Existing journal/original service calls; administrative harness, not normal authenticated MCP or chat |

These measurements separate evidence retrieval, temporal conformance, extraction
coverage and runtime stability. They do not establish natural-language answer
accuracy, tenant authorization, production capacity or safety for unseen questions.

## Results available before long-run finalization

| Check | Result | Meaning |
| --- | --- | --- |
| Latest selected-anchor coverage | SQLite 40/41; Neo4j 40/41; 10/11 complete positive cases each | Post-inspection diagnostic, not 97.6% answer accuracy |
| Exact real-claim cutoff boundaries | 236 checks, zero failures | 59 claims × two stores × immediately before/exactly at knowledge time; expanded budget isolates gating |
| Live graph contracts | 11 invariants pass | Includes future edge/intermediate/leaf proof exclusion, environment/mode isolation and repeat import |
| Live identifier contracts | Three invariants pass | Future co-mentions, edge proofs and future-dependent degree excluded |
| Local unit suite | 33 tests pass | Parser/validation/harness contracts, separate from source truth |
| Repeated frozen replay | 240 component calls, zero execution errors | Five passes over 16 cases and three methods |
| Short concurrent load | 9,379 queries in 600.125 seconds, zero failures | Four clients; p50 16.152 ms, p95 25.308 ms; stable fingerprints |
| Separate one-hour provenance run | 7,112 probes, zero failures | Pinned earlier query/fact revision; not latest-query accuracy |

At the eight-claim budget, the broad memory question still has different omissions:
SQLite misses the combined-controls experiment; graph misses an older isolated
SDK comparison. Equal aggregate scores do not mean identical or complete answers.
The specific 512MiB question initially missed its named old experiment because of
recency-only seeds. Adding word-boundary relevance before recency in **both** stores
retrieved the selected anchors for all eight specific-attempt cases. This targeted
regression is not an independent accuracy result.

A later audio original was missing from initial curation: an earlier delivered
stream was reported at 0.11 ms, while a later saved recording was reported at
0.14 ms. The latest immutable overlay retains both and a source-backed retest
relationship; neither validates a later patch or current runtime. Earlier 58-claim
runs remain labelled with their own revision. This correction is evidence that a
high selected-anchor score does not certify complete latest-state recall.

Two additional challenges deliberately used qualifiers not added to the overlay:
a larger test host versus an untested smaller target, and CPU readings from
different moments/workloads. Both direct-original paths recovered both quoted
qualifiers; both structured fact stores omitted them. The bytes were available:
**the tested extraction was incomplete**. The raw graph control uses a different
candidate scope and is not a matched latency comparison. These failures are kept,
not fixed by adding their answers merely to improve the metric.

Automatic extraction produced 54,937 identifier mentions over 1,641 identifiers.
Graph and SQL adjacency selected identical candidates for all 16 questions.
Replacing four lexical results with four neighboring messages worsened the older
40-anchor diagnostic from 5/40 to 3/40. Co-mention expansion has not shown benefit.

Semantic journal discovery reached relevant histories for several lexical misses,
but broad questions stayed ambiguous. Graph and SQL original-window expansion
returned identical selected records for all 24 vector cases. Only journals were
embedded; originals and production indexes were not changed. Query vectors were
precomputed, so the timings below exclude live query embedding. Exact selected-
quotation coverage was only 4/40 at the eight-record window budget; valid alternative
support can also miss that narrow metric. Topic discovery is not complete recall.

## Latency and production comparison

Five warm-process passes yielded these component timings:

| Component | Median | p95 |
| --- | --- | --- |
| Embedded SQLite, equal facts | 3.229 ms | 4.594 ms |
| Loopback Neo4j, equal facts | 14.767 ms | 28.643 ms |
| Lexical journal proxy | 110.257 ms | 181.362 ms |

This is a small reviewed overlay, not a fair embedded-versus-network database
capacity benchmark or an application/model latency result. An initially missing
stream/sequence composite index made graph window expansion take roughly 1–2 s.
After indexing, eight paraphrase cases had median expansion times of 17.506 ms
for Neo4j and 11.150 ms for SQLite. A real query plan confirmed an index seek.

The first production harness repeated original queries for hints naming the same
session. Its inflated aggregate timings are retained but rejected as normal agent
workflow measurements. The corrected runner deduplicated sessions, prevented
27 redundant calls and issued 17 original searches over 16 cases. Two broad
original searches still timed out. Two shorter follow-ups completed in a subsequent
trial, without establishing a production fix or answer accuracy. These are
production query findings, not failures caused or repaired by Neo4j. No production
code, indexes or migrations were changed.

## Long-run and durability status

The four-hour source/cutoff soak and separate two-hour, four-client replay are
still running. Their durations overlap and must not be added together as seven
hours of independent testing. The four-hour soak uses its original frozen query
implementation; it is not four hours of the latest relevance ranking or V7 overlay.

`finish_run.py` waits for both real study processes and verifies terminal receipts
and sample counts before restarting only the isolated graph. It then checks the
entire source projection, both pinned/current overlays, temporal boundaries,
frozen questions, live contracts and raw-original availability. The first data
query after process restart is timed before full scans, with OS page cache not
purged. Private artifacts are copied to a durable owner-only folder only after
these gates pass. Finalization and a manual audit remain pending.

## Reproduction and private artifact index

Run commands from the repository root with Python 3.12 and the dependencies in
`requirements.txt`; use the experiment virtualenv. Keep private directories mode
`0700`, files `0600`, and credentials out of shell arguments and git. Generate a
private `NEO4J_AUTH=neo4j/<random-local-password>` env file before starting Compose.

```bash
docker compose --project-name kioku-c360-temporal-poc \
  --env-file /private/neo4j.env -f scripts/temporal_graph_poc/compose.yaml up -d
python -m unittest discover -s scripts/temporal_graph_poc -p 'test_*.py'
python scripts/temporal_graph_poc/temporal_replay.py \
  --corpus /private/corpus-v3.sqlite --revision FACTS_REVISION \
  --env-file /private/neo4j.env --output /private/new-boundaries.json
python scripts/temporal_graph_poc/score_evidence.py \
  --gold /private/reviewed-evidence-gold-v3.json \
  --replay /private/frozen-16-replay-v6-latest-recording.jsonl \
  --corpus /private/corpus-v3.sqlite --output /private/new-coverage.json
```

Use each script's `--help` for its explicit frozen inputs and output paths.
Exports require an authorized SSH host and frozen owner/folder-scoped inventory;
there is intentionally no embedded production credential. `export_archive.py`
verifies committed segment bytes and optionally attachments. Stop only the same
Compose project/file; do not remove unrelated volumes or use `--remove-orphans`.

| Private receipt | Purpose |
| --- | --- |
| `snapshot.json`, `journal-attestation-v1.json` | Frozen inventory and journal-publication provenance |
| `full-original-cache-audit-v1.json`, `attachment-attestation-v1.json` | Original-byte integrity |
| `full-projection-audit-v2.json` | All-record source/locator parity |
| `facts-reviewed-v7.json`, `semantic-overlay-audit-v4-latest-recording.json` | Latest 59-claim overlay and exact graph audit |
| `reviewed-coverage-v6-latest-recording.json` | Selected-anchor coverage and missing items |
| `real-temporal-boundaries-v3-latest-recording.json` | Current exact cutoff checks |
| `component-latency-five-trials-v1.json` | Warm repeated component timings |
| `unextracted-source-visibility-v1.json`, `unextracted-raw-graph-visibility-v2.json` | Preserved extraction-loss challenges |
| `live-production-replay-v2-deduplicated.jsonl` | Corrected production comparison, including errors |
| `soak-4h-v1.jsonl`, `load-four-workers-two-hours-v1.jsonl` | Long-running sample/terminal receipts |
| `durability-finalization.json` | Gated restart/copy result, pending finalization |

Earlier failed receipts and extraction revisions remain in the private record.
They are not silently overwritten or relabelled as successful trials.
