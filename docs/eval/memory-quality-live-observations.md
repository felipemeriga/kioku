# Read-only production observations during the memory audit

Baseline: `3636866fc7094606cc1e498ad79eaf3840d72f99`, deployed backend/MCP `0.3.126`.
Observation window: 2026-11-27, approximately 05:00–05:51 UTC.
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
