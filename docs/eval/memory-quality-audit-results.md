# Kioku memory quality audit

The audit covers the frozen release `3636866fc7094606cc1e498ad79eaf3840d72f99`, with the five-hour window beginning at 04:53:34 UTC on November 27, 2026. It measures whether Kioku can recover the original records needed to answer questions about prior work. [Protocol](memory-quality-audit-plan.md) · [Reproduction](../../backend/eval/memory_audit/README.md)

**Exact evidence is harder to recover than a relevant session.** Across all 500 LongMemEval-S questions, relevance recovered at least one labeled turn in 373 of 470 answerable cases and every marked turn in 269. A looser view found a labeled session in 452 cases after accepting fifty events and deduplicating to ten sessions. In the complete LoCoMo text replay, relevance recovered a labeled turn in 996 of 1,531 eligible questions. The chronological page recovered one in 806 while finding labeled sessions more often at the same ten-event budget. Kioku-specific engineering traces confirmed explicit cutoff and provenance behavior and exposed gaps in paraphrases, the wording of past incidents, and decisions buried in activity recaps.

**Production availability changes what recall can deliver.** The read-only live check found committed segments awaiting parsing and recall indexing. Two of six convenience history probes timed out. The public corpus results below use complete isolated indexes. [Live observations](memory-quality-live-observations.md)

## Measured boundary

The benchmark imported original records with Kioku’s archive writer and verified gzip round trips. The production parser and indexing worker populated PostgreSQL 16.15 with the frozen migrations, including `search_agent_memory_v2`. Retrieval and evidence expansion entered the frozen MCP Python callable. A filesystem bucket and SQL bridge replaced the hosted Storage and PostgREST transports. The colocated runner used the published MCP 0.3.126 image, and each audit container was capped at 0.65 CPU and 768 MiB. The operational controls additionally exercised the MCP HTTP authorization middleware in process and the native chat prefetch dispatcher.

The replay received the question, fixed options and authorized scope. It received no gold labels, answer strings, or title fields that encoded evidence relevance. Metric calculation opened a separately hashed label file after retrieval. The official benchmark answer judges, model generation, production chat synthesis, and downstream environment actions were outside the measured path.

## Public evidence recovery

**Any@10** requires at least one resolvable marked original in the first ten returned events. **All@10** requires every marked original and uses a denominator with complete annotations. The relevance arm requested up to 50 events and scored the first ten. The default API chronological arm returned a ten-event page selected across dates. Its sorting is for display. The native topical prefetch already requests relevance, so the default API comparison does not represent that caller’s first search. Session metrics collapse repeated events to their first occurrence and are labeled separately.

| Corpus | Complete inputs | Relevance turn Any / All | Default turn Any / All |
| --- | --- | --- | --- |
| LongMemEval-S full release | 500 haystacks, 23,867 sessions, 246,750 turns | 373/470 · 269/470 | 273/470 · 160/470 |
| LongMemEval-S initial sample | 126 haystacks, 6,043 sessions, 62,656 turns | 75/96 · 52/96 | 47/96 · 26/96 |
| LoCoMo text | 1,986 questions, 10 dialogues, 272 sessions, 5,882 turns | 996/1,531 · 802/1,527 | 806/1,531 · 627/1,527 |
| BEAM 100K | 400 probes, 20 conversations, 90 sessions, 5,732 turns | 175/355 · 75/355 | 141/355 · 42/355 |

- **LongMemEval-S.** The initial sample selected 60 answerable primary questions, 36 answerable held-out questions and all 30 abstention probes. A separately sealed 374-question extension covered every remaining question with the same policy. All 23,867 segments indexed, yielding 405,449 searchable chunks. The both-role archive adaptation preserved whole haystacks and source timestamps. The released haystacks contain 1,475 sessions dated later than their question. This replay uses the full published histories without a question-time cutoff. At the equal ten-event budget, relevance found a labeled session for 446/470 and all labeled sessions for 384/470, compared with 445/470 and 379/470 for chronological. Taking the first ten distinct sessions from fifty events raised relevance to 452/470 and 419/470. At the literal-turn level, relevance found a target for 8/30 preference questions, 95/121 multi-session questions and 68/72 knowledge-update questions. The corresponding all-turn counts were 4, 44, and 52. Shared exact source sessions connect the full question population. The question partitions are disjoint, while their source contents overlap. The author’s reference retriever uses a different user-turn corpus. [LongMemEval release](https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/tree/98d7416c24c778c2fee6e6f3006e7a073259d48f)
- **LoCoMo.** Text and speaker identity were retained. Four answerable rows lack labeled evidence and nine have at least one malformed/unresolved literal pointer. The published captions and linked images stayed outside the index. Among the 1,540 non-adversarial questions, 697 cite at least one caption-bearing turn. With the equal ten-event budget, chronological wins on session coverage (1,412/1,531 Any) while relevance wins on exact turn recovery (996/1,531 Any). Both patterns held in all ten dialogues. [LoCoMo release](https://github.com/snap-research/LoCoMo/tree/3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376)
- **BEAM.** All 20 conversations and 400 probes from the published 100K split were replayed. The 40 abstentions and five other questions without source IDs are separate from the 355 exact-turn cases. One knowledge-update case also has an empty updated-information clause, so only 354 cases can support the all-clause metric. A chat contains at most five source sessions in this split. Its 100% session Any is a much easier test than recovering the original turn. [BEAM release](https://huggingface.co/datasets/Mohammadta/BEAM/tree/3205395e897e7318c7b094ef4e6047b9b82dbb03)

Signed expansion used at most two distinct returned sessions with one neighbor on each side and a 4,000-character per-record budget. It added 15 LongMemEval-S, 67 LoCoMo and 39 BEAM relevance cases with at least one labeled turn beyond the first ten. It added 13, 62 and 13 cases, respectively, with all marked turns. A bounded record may still exclude a needed span. All 2,991 LongMemEval-S reads, 11,907 LoCoMo reads, and 2,394 BEAM 100K reads resolved with validated source byte ranges and excerpts.

The fixed related-word policy affected 51 answerable LongMemEval-S questions and added two exact-turn Any@10 hits. It left session Any@10 unchanged and reduced literal-turn All@10 by two. In LoCoMo it affected 58 eligible questions and added one exact-turn hit while losing another. These observations apply to the short deterministic rewrite policy.

The LongMemEval-S abstention controls returned matches on all 30 queries and exposed an annotated distractor session in the relevance top ten for all 30. The LoCoMo adversarial controls returned matches on all 446 queries and exposed an annotated distractor in the relevance top ten for 262. A lexical match on an unanswerable question is plausible-looking evidence a downstream answerer must qualify.

### Larger BEAM inputs

The supplemental scale run hash-selected four complete conversations from each of the 500K and 1M splits, and one complete conversation from the 10M split. Each preserved the released question set, roles, source order and date anchors. The selected 10M conversation retained all 100 dated batches, with 54,957,629 raw JSONL bytes and 61,959 recall chunks. All segments indexed in 70.75 seconds for that conversation. All probes completed.

| Released tier | Complete conversations · probes | Indexed turns | Relevance turn Any / All | Default turn Any / All | Relevance p50 / p95 |
| --- | --- | ---: | --- | --- | ---: |
| 500K sample | 4 · 80 | 4,562 | 34/72 · 14/72 | 21/72 · 2/72 | 227 / 526 ms |
| 1M sample | 4 · 80 | 7,298 | 29/70 · 8/70 | 12/70 · 3/70 | 412 / 823 ms |
| 10M sample | 1 · 20 | 20,192 | 6/18 · 2/18 | 3/18 · 1/18 | 5.04 / 10.06 s |

The 10M relevance RPC itself took 4.96 seconds median and 9.97 seconds p95, with an 11.60-second maximum. The function’s local five-second setting did not impose a five-second outer deadline in the lab. Conversation content and probe wording differed by tier, and database size and cache state grew between runs. These complete-conversation samples describe the measured workloads. [BEAM 500K and 1M](https://huggingface.co/datasets/Mohammadta/BEAM/tree/3205395e897e7318c7b094ef4e6047b9b82dbb03) · [BEAM 10M release](https://huggingface.co/datasets/Mohammadta/BEAM-10M/tree/9b2096193fe74e2837e4713e483351e19817773c)

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

The follow-up sealed two explicit time formulations. The phrase “as of [date] at exactly 01:00:00” became a local end-of-day bound. The ISO timestamp containing `T` produced no time bound. Both yielded a record one microsecond after the requested cutoff. The direct typed `as_of` argument retained the exact cutoff and hid that record. Separately, “As of [date], what did we work on?” selected the overview projection together with `as_of` and returned `invalid_overview_arguments`. These are caller routing failures at the supplied evidence stage.

Other controlled checks established the following limits and provenance:

- Three native search citation URLs and three expanded evidence URLs mapped to the exact synthetic folder, session and event. The expanded center kept its citation number.
- Content-only Portuguese terms failed to retrieve a known Portuguese original both with accents and after transliteration. Its unchanged ASCII identifier retrieved it.
- A 100-folder key scope succeeded in the lab. Adding one repository made both the broad request and an explicit named-repository request return `scope_too_broad`. A key restricted directly to that repository succeeded.
- A journal with 2,050 entries returned 2,000 visible entries and `inventory_limit_reached_narrow_dates`. Opening the unchanged journal reference returned `journal_revision_changed_search_again`. The observed over-cap case had no intervening revision.
- Fourteen LongMemEval-S sentinels kept the same first ten event identities and order with both ten- and fifty-event limits after the archive grew. Five warmed repetitions per case per limit kept the ranking stable. A second ten-event page had no duplicates with the first page in this sample.

## Latency boundary

Latency is wall time entering the MCP callable and reading its serialized result on the colocated lab. PostgreSQL bridge timing includes the same-host client round trip. The component sum adds the actually issued bounded reads to discovery and optional deterministic rewriting. It excludes external MCP/HTTP, hosted Storage/PostgREST, agent orchestration and model answers. The median and p95 below use all attempts and nearest-rank p95. First invocation and warmed sentinel results are reported separately from uncontrolled corpus queries because the database cache was not flushed.

| Corpus · relevance | Attempts | Discovery p50 / p95 | Discovery plus bounded reads p50 / p95 |
| --- | ---: | ---: | ---: |
| Initial LongMemEval-S | 126 | 46.4 / 95.5 ms | 64.5 / 111.0 ms |
| LongMemEval-S extension | 374 | 44.3 / 158.9 ms | 63.9 / 180.9 ms |
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

Two follow-up one-session serial inputs held the 4,096 records and 64 segments. The all-message workload fully indexed in 5.41 seconds. The original role mix with distinct tool-result identities fully indexed in 3.18 seconds. Parser publication p95 was 130.3 ms and 44.4 ms, respectively, across 64 calls each. The largest delay appeared when repeated tool-result identities were concentrated in one session.

Five warmed broad queries in the fully indexed four-session cells returned 3,072 events and took 171–174 ms median. Appending one strong identifier reduced the final count to one while leaving the medians at 179–192 ms. Narrowing the date reduced the result set to 48 and the medians to 54–87 ms. These are fixed-case timings on a synthetic workload, with SQL and dependency calls measured inside the same container boundary.

## Standards coverage

| Standard | Execution completed | Other layers |
| --- | --- | --- |
| LongMemEval-S | All 500 complete haystacks and original-evidence retrieval | Official generated-answer scoring and the M/oracle variants |
| LoCoMo | All ten published dialogues and 1,986 text QA probes | Generative QA, image bytes, event summarization and multimodal generation |
| BEAM | All 20 conversations and 400 original-evidence probes in 100K, plus nine complete conversations and 180 probes from the larger splits | Official generated-answer judge and a census of larger splits |
| MemoryAgentBench | Four full FactConsolidation contexts and 800 source-string probes | Official task-answer score and other sub-benchmarks |
| STATE-Bench | Twelve published training transcripts selected across travel, shopping and support | Simulated customer workflows, held-out environments and completion |
| MemoryArena | Twelve published travel histories through the prefix before the last subtask, with 24 retrieval probes | Solving later subtasks, environment feedback, success rate and progress |

For the STATE training replay, relevance found at least one of the final tool call/result in three of twelve transcripts and recovered both in zero. Two signed reads did not improve those counts. The corpus retained actual recorded tool outcomes with synthetic call IDs. For MemoryArena, every history prefix fit within ten records. All 24 probes recovered all their marked inputs. These were the published initial itinerary and earlier user prompts. The lab did not produce a travel action or observe its result. [STATE-Bench training trajectories](https://github.com/microsoft/STATE-Bench/tree/5644b1838d96bc4483da29642d058ecaa6f80f7f/datasets/train_task_trajectories) · [MemoryArena travel inputs](https://huggingface.co/datasets/ZexueHe/memoryarena/tree/da1a37c8b19280e18627ca01cf368195a5e1d92e/group_travel_planner)

## Verification and outputs

The frozen edit scope contains evaluation code, an audit CI check and documentation. The production service, SQL, inference configuration and deployed containers were untouched. The focused archive, history, prefetch, period-report and audit test selection passed 292 tests. Thirty-two existing CLI capture and journal tests and five PostgreSQL-WASM fixture suites also passed. The live observations document supplies the distinct production check.

| Run | SHA-256 of sealed manifest | SHA-256 of raw replay metadata |
| --- | --- | --- |
| Initial LongMemEval-S | `98ea803827cb05da9cb2b5295c1f5bed819dbf1e4035895edb647543a7fab4ee` | `350cd260ad916fc5313d705a99f302146f2ad308437afcad80d7b5d01112caae` |
| LongMemEval-S extension | `ac80419e6addd2e54cecc48d27668a1d9a7f78f319468b7e598cce2c6d8eb242` | `2eceac8d60d20a38fd95f631ad80016609ac1230a659d69ac5f3865769ad7612` |
| LoCoMo | `98ea803827cb05da9cb2b5295c1f5bed819dbf1e4035895edb647543a7fab4ee` | `4413506f536732aba6273600c84133e2a44d22e9e0c11f7f688a56188a9d0705` |
| BEAM 100K | `8a29e0c026b0d24fdffe39da09d91d01a24776750f2f9806c5d0752e028e319e` | `4712c00a2ee2fc2a14f0f38049b8ce5af6e9ad1cc8baee36043e79730254a6ca` |
| BEAM 500K sample | `1b3930d17dc8987b70f0c0db8bb72a1d018156c902943829cff519a9af6b0310` | `0e7940b61598bf44bcbfd03885fa997521b6a67ff0a645b4c7720ea3c6579122` |
| BEAM 1M sample | `6f16de4f3673d0c8cbb5085dbb3c1828dd72f0e866b8ec6aad7d3bcc403b1643` | `ddb8b3d629ee38c954f2dd1a872399ee0babd23799b7911e4be0bf69ce263cbb` |
| BEAM 10M sample | `444373b7921561ce1c8b485bfc2e32ba66ea611ce7c8273063bc487aa8fb28eb` | `3c1ccdd32d99128e5f3f4b6bc7cb7ff57dd9a47d192348864cd49c6cfca76482` |
| FactConsolidation | `b8f900398be0e84e667e4313d08512c8442e0122f7c2278d900fd2b4aa13d975` | `f87c80e3e439186c79c380785cc23354708dc71a84f1e68a69008758baa7c067` |
| Operational fixtures | `b02b8af513ed80a11496a7a9a2b21f5186b900bc0b50da08d938f2d6dea07e33` | `18b83ab193398b82404c73e42c4220a450d98fb2d6ac4b6233905efcb77b0a9d` |
| 4,096-record liveness control | Fixed synthetic generator | `620b3243ceb2df9d839694e115b5794ef1f8e84994036ee5f7284d5816cfbf39` |
| STATE training replay | `648393a54003ef566f4e0eb74f788e134360acb2e702239d33fac94a9afc8251` | `1fe00bb01022f3de390f870455da3d7cc5263ca7841b4eb83c6adae4cdfb9ec3` |
| MemoryArena prefixes | `b0388ee57fe29c47b0fa14dc29e75ed2cc528674d3fc1c6d7e5f38dbb4dd7c81` | `6f829ce7d5bf5536b239606038ef25cc2159e7a06a223ad30b0d1cd83640c54e` |

Raw source, per-query labels, payload text and credentials stay outside the pull request.

## Priorities supported by the measurements

1. **Measure the path from capture to searchable evidence.** A committed manifest, parsed locator and searchable original are separate states. Track oldest pending work and progress through each stage so worker uptime and a healthy release cannot mask an indexing backlog. Use the concentrated and duplicate-worker fixtures to validate proposed publication changes alongside the real archive counters. [Live observations](memory-quality-live-observations.md)
2. **Keep exact-turn and source-set recall visible.** Session coverage and exact originals reward different selection behavior. Retain both metrics, use equal budgets, and test the paired command/result and revision cases before changing default ordering.
3. **Preserve the user's temporal intent.** Add incident-date, as-of, completed-week and month-end wording to caller regression checks. Prepared scope and record-time cutoffs should survive the initial route, follow-up searches and citation expansion.
4. **Target lexical misses with a measured caller policy.** Use the sealed paraphrase, Portuguese and unseen-identifier controls to judge the gain from any semantic fallback against added time and distractors. The small fixed rewrite policy alone had limited coverage.
5. **Measure answers and work completion as separate experiments.** An answer benchmark should give the same named caller the same authorized corpus with and without recalled evidence. Grade grounded claims, qualified abstention and matched task state. Published STATE-Bench and MemoryArena require their environment or simulator and scoring, beyond the history-tool interface.
