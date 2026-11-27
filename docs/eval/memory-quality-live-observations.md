# Read-only production observations during the memory audit

Baseline: `3636866fc7094606cc1e498ad79eaf3840d72f99`, deployed backend/MCP `0.3.126`.
Observations began on 2026-11-27 at approximately 05:00 UTC; individual checkpoints are recorded below.
These are convenience probes and operational observations, not independently labeled benchmark scores.
No production data, configuration, keys, indexes, or services were changed for these checks.

## Archive availability

The requested account had 83 active archive sessions and 8,530 committed active segment objects at 05:03 UTC. Of these, 2,908 had a parser version below 1 and a memory-index version below 2. Segment counts do not estimate the percentage of unavailable knowledge: segment size, duplicates, coverage, predecessor dependencies, and overlapping source material differ.

Worker maintenance logs contained database lock errors (`55P03`) and statement cancellation/timeouts (`57014`) while calling `publish_agent_evidence_index`. These are observed indexing failures, distinct from query relevance failures. A sampled pending object downloaded with its expected hash and parsed locally, so this observation does not establish loss of original bytes.

Maintenance is scheduled every 30 seconds; observed jobs took approximately 48–99 seconds with capacity for three worker jobs. Source inspection shows session row locking and a full-session correlated tool-result deduplication update in each publishing call. The checked migration set has no index keyed by `call_id` on the events table. These are candidate explanations requiring controlled reproduction, not an established root cause. The deployment diff did not change this indexing path.

## Six fixed real-user questions

Questions were frozen before execution, drawn from the user-visible conversation, and restricted to the owned Kioku folder. The six questions covered unavailable originals, subscription authentication, historical weekly cutoffs, documentation versus code, realistic latency testing, and centralized versus local secrets. No exhaustive gold evidence set was available, so a returned result is not counted as a correct answer.

Boundary: installed CLI → fresh public MCP transport → deployed services and live Supabase/storage; sequential execution, one attempt per frozen question, 25-second client cap.

| Question family | Outcome | Wall time |
| --- | --- | ---: |
| Unavailable originals | `evidence_query_timeout` | 9.19 s |
| Subscription choice | 10 matches returned | 11.78 s |
| Weekly historical cutoff | 10 matches returned | 22.02 s |
| Documentation/code source roles | `evidence_query_timeout` | 9.30 s |
| Realistic latency testing | 10 matches returned | 11.14 s |
| Centralized versus local secrets | 10 matches returned | 10.89 s |

Successful responses reported 5,277–10,058 total matches and 776 pending objects in scope. This small selected set is not an estimate of general failure rate or latency percentiles. It does establish that production reliability/latency remains a separate concern even when the isolated public replay completes without errors.

The existing Codex MCP transport separately returned HTTP 403, “MCP session does not belong to this API key scope,” before invoking search. A fresh CLI transport reached the service. This client-session mismatch is not scored as a retrieval miss; no keys or client configuration were modified.

## One instrumented successful service call

A subsequent read-only replay of the centralized/local-secrets question used the backend service directly, with the same owned folder and query filters. It bypassed CLI/MCP authentication and public transport. The archive was live and changing, and cache state was uncontrolled.

- Total service wall time: 5,727 ms.
- Main `search_agent_memory_v2` RPC: 2,141 ms.
- Eight other measured sequential table operations: approximately 1,888 ms combined.
- Remaining approximately 1,698 ms includes storage, projection/decompression, Python work, and uninstrumented calls; it cannot all be attributed to storage.
- Result: 10 matches, 5,282 total candidates, 779 pending objects.

This identifies substantial database and dependent-call costs in one observed request. It does not isolate network from database execution time inside an RPC, and the earlier CLI time cannot be subtracted to derive authentication overhead because the observations were neither simultaneous nor cache-controlled. Isolated near-database benchmark times must not be presented as production end-to-end latency.

## Source-based routing controls

A separate pure-function diagnostic exercised history-prefetch routing without generating answers. English “have we ever tried” and explicit weekly/monthly questions were recognized. Several Portuguese formulations and English “remember why we rejected” formulations were not recognized. Native chat can still recover by calling memory tools; prefetch misses are not final answer failures.

An incident date embedded in a question such as “Have we fixed the SSE outage from 2026-11-12?” was interpreted as a one-day search filter. Such narrowing can exclude a later resolution. Source-time cutoff tests and final-status questions should explicitly cover this ambiguity.

Raw private outputs and fixture hashes are retained outside Git under the audit artifact directory. This report intentionally contains no original transcript text, access tokens, credentials, or signed evidence references.

## Follow-up snapshot at 05:50–05:51 UTC

Read-only counts still showed 83 active sessions: 8,694 committed segment objects, with 2,973 pending parser indexing and 2,973 pending memory indexing. The earlier 05:03 counts were 8,530 committed and 2,908 pending. These are separate, non-transactional metadata observations over a changing archive, not an estimate of lost records, unique unavailable facts, or a forecast of drain time.

All seven Kioku containers were running on the same release images, with zero recorded restarts and no OOM kills. Worker logs since 05:00 contained 33 `55P03` and 19 `57014` RPC-error entries. The counts are log occurrences, not unique failing objects or users. Running containers do not establish indexing liveness.

## Frozen real developer-history probes

A later audit phase sealed twelve questions against the actual native Kioku conversation, with one verbatim user question and eleven retrospective/paraphrased questions. They span recorded requirements, assistant reports, two observed command results and a source listing. The source roles remain distinct: an assistant report is not proof of deployment. Query SHA-256: `9f46ea521cd88f243160dedca11d194598858907bbb013ee75487bf3d388c1e9`.

Every query searched the authorized Kioku repository, with relevance order, a ten-result page and the common typed cutoff `2026-11-27T04:53:34Z`. No target session ID or gold evidence was supplied to the caller. The cutoff excludes new audit questions and labels from their own retrieval. A separate read-only metadata join confirmed all 34 acceptable alternative anchor IDs were present, displayable, non-inherited and chunk-backed, across eleven fully parsed/indexed objects. The source ledger and selected compressed-segment hashes were independently checked against the native original before execution.

Seven searches returned `evidence_query_timeout`; five returned results. Among the five completed searches, one surfaced its specific known anchor and expanded it successfully. The other four returned records outside the labeled set. This is **known-anchor exposure**, not a generated-answer score or exhaustive relevance judgment. Other returned records may legitimately support an answer. Timeouts are censored retrieval outcomes, rather than accuracy misses. The first attempted harness launch ran outside a connected CLI repository and failed locally; it made no public search calls and is retained separately. The connected run kept the same sealed queries and gold.

Nine signed reads returned successfully. Of their thirty returned records, twenty-two belonged to the frozen parent and were independently matched to local source projections/locators. The remaining eight came from other authorized sessions and were not compared against this parent file. The one recovered case had two native representations of the same user statement, which count as one question-level success.

The blinded wording follow-up retained the same source cutoff and labels. Its query author saw only the question file, then sealed five Portuguese-to-English translations, seven byte-identical English repeat controls, and twelve concise keyword variants. The English arm completed 4/12 searches with eight typed query timeouts; the keyword arm completed 8/12 with four typed timeouts. Neither arm exposed a frozen anchor. All eight English signed reads succeeded; fifteen of sixteen keyword signed reads succeeded, with one failure whose structured reason was not retained. Source availability stayed complete for the known anchors. More completed keyword queries did not establish more supporting evidence or better answers. These are dependent repeated topics, with changing production state and potentially useful unlabeled records; they do not establish a causal language or latency improvement.

The original successful searches took 16.0 seconds median (n=5); search plus issued signed reads took 29.1 seconds median. English-arm completed searches had a 14.5-second median (n=4), and keyword-arm completed searches a 13.5-second median (n=8). Their differing completed subsets and failure censoring preclude a direct speedup claim.

The typed cutoff specifically suppresses journal activity. These topical queries would omit period reports even without the cutoff. The experiment does not grade the ordinary enriched chat flow, briefing context, or current code/knowledge-base answers. The verbatim question about editing managed instructions can appropriately be answered from current CLI source rather than its selected historical record.

## MCP session lifecycle and request overhead

A small authenticated live probe used two newly created, owned MCP sessions. It did not restart a service, rotate a key, change configuration, or invoke a model. With the same valid key, it initialized a session, terminated it normally with HTTP DELETE, and then attempted a read-only ping bearing that terminated session identifier. The server returned HTTP 403 with the scope-mismatch message. A subsequent fresh initialization using the unchanged key succeeded.

The middleware's in-memory binding map treats an unknown/terminated session and a known session belonging to another scope as the same rejection branch. This also explains why a server restart can produce that error, although the cause of the earlier pre-existing client failure was not independently observed. The MCP transport specification requires 404 for a terminated session and describes starting a new initialization after that response. The observed 403 therefore obstructs the protocol's recovery path; changing it does not by itself prove that every client will automatically retry correctly. [MCP session management](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports#session-management)

In this single Python-SDK probe, initialization took 1.32 seconds and normal transport termination 1.17 seconds. Authenticated request response headers generally arrived after about 1.2 seconds. These are time-to-header measurements, not database execution times; an open SSE request's lifetime is not a server-processing metric. Two identical no-match history calls returned a tool error in 9.60 seconds (its detail code was not retained) and a successful empty result in 2.88 seconds. The fresh initialization after the terminated-session check took 0.88 seconds. This is a small lifecycle diagnostic with uncontrolled deployment/cache state, not a latency percentile estimate or a trace of the installed CLI's exact SDK sequence.

Source review identifies repeated authenticated database checks and descendant-folder traversal on each HTTP request; the history dispatcher then resolves descendants again. Their actual contribution must be measured before prescribing a cache or weakening authorization. The session lifecycle result is independently actionable while preserving cross-owner and cross-scope denials.

## Archive snapshot at 07:12 UTC

The same read-only active-owner query returned 83 active sessions, 8,901 committed segments, and 3,057 pending both parser and memory indexing. The earlier snapshots remain separate observations of the changing archive; no production repair or parameter change was made.
