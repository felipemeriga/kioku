# Kioku memory quality audit

The audit covers the frozen release `3636866fc7094606cc1e498ad79eaf3840d72f99`, with the five-hour window beginning at 04:53:34 UTC on November 27, 2026. It measures whether Kioku can recover the original records needed to answer questions about prior work. [Protocol](memory-quality-audit-plan.md) · [Reproduction](../../backend/eval/memory_audit/README.md)

**Exact evidence is harder to recover than a relevant session.** In the complete LoCoMo text replay, relevance search recovered at least one labeled turn in 996 of 1,531 eligible questions. The chronological page recovered one in 806. The chronological page found at least one labeled *session* more often at the same ten-event budget. In Kioku-specific engineering traces, the service handled explicit cutoffs and provenance correctly, while paraphrases, the wording of past incidents, and decisions buried in an activity recap exposed retrieval gaps.

**Production availability changes what recall can deliver.** The read-only live check found committed segments awaiting parsing and recall indexing. Two of six convenience history probes timed out. The public corpus results below use complete isolated indexes. [Live observations](memory-quality-live-observations.md)

## Measured boundary

The benchmark imported original records with Kioku’s archive writer and verified gzip round trips. The production parser and indexing worker populated PostgreSQL 16.15 with the frozen migrations, including `search_agent_memory_v2`. Retrieval and evidence expansion entered the frozen MCP Python callable. A filesystem bucket and SQL bridge replaced the hosted Storage and PostgREST transports. The colocated runner used the published MCP 0.3.126 image, and each audit container was capped at 0.65 CPU and 768 MiB. The operational controls additionally exercised the MCP HTTP authorization middleware in process and the native chat prefetch dispatcher.

The replay received the question, fixed options and authorized scope. It received no gold labels, answer strings, or title fields that encoded evidence relevance. Metric calculation opened a separately hashed label file after retrieval. The official benchmark answer judges, model generation, production chat synthesis, and downstream environment actions were outside the measured path.

## Public evidence recovery

**Any@10** requires at least one resolvable marked original in the first ten returned events. **All@10** requires every marked original and uses a denominator with complete annotations. The relevance arm requested up to 50 events and scored the first ten. The default chronological arm returned a ten-event page selected across dates. Its sorting is for display. Session metrics collapse repeated events to their first occurrence and are labeled separately.

| Corpus | Complete inputs | Relevance turn Any / All | Default turn Any / All |
| --- | --- | --- | --- |
| LongMemEval-S initial sample | 126 haystacks, 6,043 sessions, 62,656 turns | 75/96 · 52/96 | 47/96 · 26/96 |
| LoCoMo text | 1,986 questions, 10 dialogues, 272 sessions, 5,882 turns | 996/1,531 · 802/1,527 | 806/1,531 · 627/1,527 |
| BEAM 100K | 400 probes, 20 conversations, 90 sessions, 5,732 turns | 175/355 · 75/355 | 141/355 · 42/355 |

- **LongMemEval-S.** The initial frozen sample selected 60 answerable primary questions, 36 answerable held-out questions and all 30 abstention probes. The both-role archive adaptation preserved whole haystacks and source timestamps. It did not impose the question date as a cutoff. The source contains sessions dated later than the question, including 370 in the initial sample. In the equal ten-event view, relevance found a labeled session for 87/96 and all labeled sessions for 75/96, compared with 86/96 and 78/96 for chronological. Allowing 50 events before deduplicating and taking ten distinct sessions raised relevance to 89/96 and 83/96. Shared exact source sessions connect the sample questions, so query-disjoint holdouts are not source-disjoint validation. The author’s reference retriever uses a different user-turn corpus. [LongMemEval release](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/tree/98d7416c24c778c2fee6e6f3006e7a073259d48f)
- **LoCoMo.** Text and speaker identity were retained. Four answerable rows lack labeled evidence and nine have at least one malformed/unresolved literal pointer. The published captions and linked images stayed outside the index. Among the 1,540 non-adversarial questions, 697 cite at least one caption-bearing turn. With the equal ten-event budget, chronological wins on session coverage (1,412/1,531 Any) while relevance wins on exact turn recovery (996/1,531 Any). Both patterns held in all ten dialogues. [LoCoMo release](https://github.com/snap-research/LoCoMo/tree/3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376)
- **BEAM.** All 20 conversations and 400 probes from the published 100K split were replayed. The 40 abstentions and five other questions without source IDs are separate from the 355 exact-turn cases. One knowledge-update case also has an empty updated-information clause, so only 354 cases can support the all-clause metric. A chat contains at most five source sessions in this split. Its 100% session Any is a much easier test than recovering the original turn. [BEAM release](https://huggingface.co/datasets/Mohammadta/BEAM/tree/3205395e897e7318c7b094ef4e6047b9b82dbb03)

Signed expansion used at most two distinct returned sessions with one neighbor on each side and a 4,000-character per-record budget. It recovered an additional 67 LoCoMo and 39 BEAM relevance cases with at least one labeled turn beyond the first ten and added 62 and 13 cases, respectively, with all marked turns. This is measured evidence exposure. The model may still miss a supporting span within a bounded record. All 753 initial LongMemEval-S reads, 11,907 LoCoMo reads, and 2,394 BEAM 100K reads resolved with validated source byte ranges and excerpts.

The fixed related-word policy affected ten answerable LongMemEval-S sample questions without changing exact-turn Any@10. In LoCoMo it affected 58 eligible questions and added one exact-turn hit while losing another. These observations apply to the specific, short deterministic rewrite policy.

The LongMemEval-S abstention controls returned matches on all 30 queries and exposed an annotated distractor session in the relevance top ten for all 30. The LoCoMo adversarial controls returned matches on all 446 queries and exposed an annotated distractor in the relevance top ten for 262. A lexical match on an unanswerable question is plausible-looking evidence a downstream answerer must qualify.

### FactConsolidation

MemoryAgentBench’s Conflict Resolution file supplied four full context sizes for the single- and multi-hop FactConsolidation tasks. All 800 probes ran across those four contexts. Every accepted answer string occurred somewhere in its full context. In the first ten returned original records, relevance found a case-insensitive accepted substring for 392/400 single-hop and 65/400 multi-hop questions. Chronological found 394/400 and 85/400, respectively. The file lacks source turn annotations. Common values may appear in irrelevant statements, and finding a substring cannot establish that the correct current fact was selected. [MemoryAgentBench release](https://huggingface.co/datasets/ai-hyz/MemoryAgentBench/tree/7ea066982b140a19337e17e60d45d4076e042faf)

## Operational evidence

Twenty-six frozen questions used 45 synthetic native records, ten dated journal entries, two versions of a weekly report and a mix of Codex and Claude record forms. The same database and evidence signer handled search, read and authorization. Each ordinary arm had a ten-event page and up to two signed reads. The native prefetch arm used the release’s own routing, date extraction and follow-up policy.

| Scenario | Observed behavior |
| --- | --- |
| Cross-repository week and month | Weekly inventory contained five journal groups and twelve original session-days. The completed-month inventory contained eight journal groups and twenty-one original session-days. Both included an originals-only repository, returned three repositories and reported complete inventory. Reading the week’s final report resolved its signed original citation. |
| “What did we actually ship last week?” | No arm surfaced the known release observation. The separate probe with the release ID recovered the production observation, both observed test runs and the billing-blocked CI workflow. |
| “Have we ever tried avoiding a full rebuild?” | Literal search and default prefetch found one of two host outcomes. The fixed related-word policy found both. Two differently worded English questions and the Portuguese variant missed both; the Portuguese question also routed away from history. |
| Incident date versus historical cutoff | Direct recall surfaced the initial diagnostic and later fix. Native prefetch bounded “Have we fixed the outage from [date]?” to the incident day and supplied only the diagnostic. The explicit day-as-of query retrieved the diagnostic and excluded later outcomes. |
| Remembering a rationale | Direct recall surfaced the source. “Remember why we chose …?” started on knowledge search. “What did we decide … and why?” started on history and surfaced the source. |
| Update, revert and approval | The month-end cutoff preserved the merge, revert and open follow-up while excluding the December fix. The approval probe found the observed pending gate despite a contradictory assistant statement. |
| Time and provenance | Direct exact timestamp cutoff included the equal-time record and excluded a record one microsecond later. The midnight cutoff excluded the later paired tool result. The two local 01:30 records on the daylight-saving boundary both resolved. A late import carrying an earlier source timestamp became available under an existing reference, while its post-cutoff sibling stayed excluded. Signed references bind source-time bounds and authorization. They do not freeze ingestion state. |
| Permission and integrity | Missing/invalid MCP key returned 401. Session reuse under another key scope returned 403. Signed references failed under another owner even in a valid separate session. Tampering was rejected. A long UTF-8 original was reconstructed over nine pages beginning at a nonzero offset. A deliberately changed archive object produced `object_integrity_failure`. |
| Recoverable index gap and attachment | A committed unindexed segment reported one pending object and yielded no recall hit. The same unchanged original became searchable after the real worker ran. The attachment checksum matched on download. Its attachment-only text was outside the original-text search corpus. |

The first operational invocation stopped at a whitespace compatibility error in the audit bridge’s parsing of a selected column list. The second invocation used a fresh synthetic namespace, retained the question design, corrected the mock calendar for the completed-month cases and exercised the full controls. Those harness changes did not touch product code. A prefetch-only comparison in the second invocation lacked explicit timestamp wording, so the direct cutoff test was valid and its prefetch comparison did not establish an exact-time failure.

## Latency boundary

Latency is wall time entering the MCP callable and reading its serialized result on the colocated lab. PostgreSQL bridge timing includes the same-host client round trip. The component sum adds the actually issued bounded reads to discovery and optional deterministic rewriting. It excludes external MCP/HTTP, hosted Storage/PostgREST, agent orchestration and model answers. The median and p95 below use all attempts and nearest-rank p95. First invocation and warmed sentinel results are reported separately from uncontrolled corpus queries because the database cache was not flushed.

| Corpus · relevance | Attempts | Discovery p50 / p95 | Discovery plus bounded reads p50 / p95 |
| --- | ---: | ---: | ---: |
| Initial LongMemEval-S | 126 | 46.4 / 95.5 ms | 64.5 / 111.0 ms |
| LoCoMo | 1,986 | 31.0 / 49.9 ms | 46.8 / 71.0 ms |
| BEAM 100K | 400 | 78.8 / 177.2 ms | 94.8 / 193.3 ms |

The tunneled laptop-to-lab PostgreSQL round trip was 134 ms median over 50 uncached-at-caller `SELECT 1` calls. Public benchmark measurements were subsequently colocated and omit that network hop. The live convenience probes used local CLI → public MCP → hosted dependencies. Four succeeded in 10.9–22.0 seconds and two returned `evidence_query_timeout`. They describe the live archive and transport rather than the lab corpus. [Live observations](memory-quality-live-observations.md)

### Index throughput and query shape

The synthetic workload first committed 64 segments containing 4,096 records. Each four-record unit included a user message, a tool call, and short and rich representations of the same tool response. The existing parser deduplicated the visible tool result to leave 3,072 displayable events. The experiment held record and segment counts fixed and assigned them to one or four sessions. Workers independently called the normal `process_session` code. Duplicate assignments model overlapping scans of the same work. Each cell ran once, in the displayed order, under the same CPU cap. Database cache state and accumulated fixture volume can vary across cells.

| Work distribution | Workers | Parsed / recall indexed at last worker return | Last worker return | Parser publication p95 |
| --- | --- | --- | ---: | ---: |
| One session | One | 64/64 · 8/64 | 128.5 s | 6.29 s (64 calls) |
| One session | Two overlapping | 64/64 · 8/64 | 322.2 s | 12.42 s (128 calls) |
| Four sessions | One | 64/64 · 64/64 | 8.69 s | 269.9 ms (64 calls) |
| Four sessions | Two disjoint | 64/64 · 64/64 | 7.55 s | 495.3 ms (64 calls) |
| Four sessions | Two overlapping | 64/64 · 64/64 | 26.85 s | 1.00 s (128 calls) |

The 120-second cooperative stop requested an end between worker calls. Near that point, the one-session cells had parsed 62 and 42 segments respectively. Neither had published a searchable segment yet. The in-flight passes finished parsing and each condition ended with eight searchable segments, so the last-worker timings are incomplete-drain observations. The one-session overlap registered 1,119 sampled transaction-ID waits through the stop request. These are repeated samples of active connections. All three completed four-session cells passed the first/last object checksum and idempotency checks. The lab emitted no SQLSTATE failures. These controlled results establish that concentration and redundant workers increased time and contention in this fixture. Production backlog and SQLSTATE failures remain separate observations.

Five warmed broad queries in the fully indexed four-session cells returned 3,072 events and took 171–174 ms median. Appending one strong identifier reduced the final count to one while leaving the medians at 179–192 ms. Narrowing the date reduced the result set to 48 and the medians to 54–87 ms. These are fixed-case timings on a synthetic workload, with SQL and dependency calls measured inside the same container boundary.

## Verification and outputs

The frozen edit scope contains evaluation code and documentation. The production service, SQL, inference configuration and deployed containers were untouched. The focused archive, history, prefetch, period-report and audit test selection passed 268 tests. The project’s five PostgreSQL-WASM fixture suites also passed. The live observations document supplies the distinct production check.

| Run | SHA-256 of sealed manifest | SHA-256 of raw replay metadata |
| --- | --- | --- |
| Initial LongMemEval-S | `98ea803827cb05da9cb2b5295c1f5bed819dbf1e4035895edb647543a7fab4ee` | `350cd260ad916fc5313d705a99f302146f2ad308437afcad80d7b5d01112caae` |
| LoCoMo | `98ea803827cb05da9cb2b5295c1f5bed819dbf1e4035895edb647543a7fab4ee` | `4413506f536732aba6273600c84133e2a44d22e9e0c11f7f688a56188a9d0705` |
| BEAM 100K | `8a29e0c026b0d24fdffe39da09d91d01a24776750f2f9806c5d0752e028e319e` | `4712c00a2ee2fc2a14f0f38049b8ce5af6e9ad1cc8baee36043e79730254a6ca` |
| FactConsolidation | `b8f900398be0e84e667e4313d08512c8442e0122f7c2278d900fd2b4aa13d975` | `f87c80e3e439186c79c380785cc23354708dc71a84f1e68a69008758baa7c067` |
| Operational fixtures | `b02b8af513ed80a11496a7a9a2b21f5186b900bc0b50da08d938f2d6dea07e33` | `18b83ab193398b82404c73e42c4220a450d98fb2d6ac4b6233905efcb77b0a9d` |
| 4,096-record liveness control | Fixed synthetic generator | `620b3243ceb2df9d839694e115b5794ef1f8e84994036ee5f7284d5816cfbf39` |

Raw source, per-query labels, payload text and credentials stay outside the pull request.
