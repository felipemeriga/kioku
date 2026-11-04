# Native Claude Code research results

## Outcome

The local native subscription POC completed both real three-hour runs. Native
Claude Code can supply model/tool rounds for isolated Mihari maintenance and
streaming conversations. It needs an application adapter; the coding harness is
not a direct replacement for Kioku's agent contract.

The initial server phase found expired native authentication. After the operator
completed native login, the follow-up passed live host/container conversation and
Mihari tests. See [SERVER_RESULTS.md](SERVER_RESULTS.md) for measurements,
container restart recovery, deployment examples and unattended auth operations.

Nothing in this branch changes production application code, routes, billing,
briefings, journals, or conversations. The PR stays draft.

## Duration and scope

| Run | UTC start | UTC finish | Actual monotonic seconds | Work |
| --- | --- | --- | ---: | --- |
| Evolving repo/chat soak | 2026-11-03 21:47:04 | 2026-11-04 00:47:04 | 10800.011 | 60 cycles, 3 synthetic Git repos |
| Persistent stream-json | 2026-11-03 21:49:31 | 2026-11-04 00:49:32 | 10800.540 | 60 turns, 3 forced worker replacements |

Recorded 569 one-shot native calls across experiments, plus 60 successful
persistent turns. Some one-shot calls deliberately fail or are cancelled.
The superseded first persistent trial is retained separately, not counted as
successful. Representative work ran periodically throughout the three hours;
the duration was not simulated.

Local CLI: 2.1.285, existing claude.ai Max native sign-in, API fallback variables
removed. Server CLI: 2.1.207. The `haiku` alias resolved to Haiku 4.5; `sonnet`
resolved to Sonnet 5.5, and `opus` to Opus 5.5. Explicit Sonnet 4.6 also worked.
Model/version pinning matters when comparing results.

## Measured behavior

| Check | Result |
| --- | --- |
| Persistent architecture decisions | 60/60 current facts recalled |
| Persistent forced replacement/resume | 3/3 recoveries |
| Repeated bounded fanout | 33/33 calls; all 12 configurations isolated correctly |
| Full local Mihari main/process_repo fixture adapter | 7 checks passed: polling/clone/fetch, per-repo sessions, unchanged HEAD gating, SHA retention on failure, recovery, persisted docs |
| Standalone localhost SSE chat | Stateless history, stateful resume, client disconnect persistence, responsive concurrent reads, same-chat exclusion passed |
| Stream input different session_id | Does **not** isolate a new conversation; same native process retained original session |
| Concurrent resume same session | Both native calls accepted; host must enforce serialization |
| Cross-working-directory resume | Succeeded with native session storage available |
| Nonpersisted session resume | Rejected as expected |
| Turn budget exhausted before answer | Native error_max_turns; explicit host fallback succeeded |
| Native safe mode with explicit fixture MCP | Explicit MCP omitted in this CLI version |
| Native bare mode | Documented to skip OAuth; unsuitable for this subscription POC |

The real Mihari dispatcher and actual `main/process_repo` ran against local Git
remotes. Supabase, KMS/auth, and graph/embedding upload were isolated local
adapters. The fixture MCP is read-only lexical source retrieval plus AST graph
lookup; this is not a Voyage search-quality or production embedding benchmark.

Local HTTP chat continued generating after its simulated browser disconnected:
the client received one character, while the completed 1,955-character answer
was retained by the server. During a real native generation, a state GET took
2.09ms and another turn on the same conversation was rejected.

## Failures and fixes

The main soak had one parser failure: requested JSON included trailing prose.
Native `--json-schema` fixed the parsing path; the supervisor resumed its
checkpoint with the original monotonic start intact. A valid JSON object can
still select the wrong briefing sections; enums and source-aware validation
remain necessary.

Of 60 cycles, 51 passed every simple assertion. Besides the parser failure,
6 explicit-history exact-token checks and 2 artificial parallel string-output
checks failed. These were model refusals or identifier truncation, not detected
cross-session leakage. Every stateful recall and stateless no-history isolation
check that ran passed. A controlled follow-up reproduced default coding-prompt
exact recall at 3/4, versus 4/4 with a custom Kioku grounded system prompt.
Those small samples do not establish perfect reliability.

The first persistent token-only experiment triggered a false prompt-injection
refusal. The realistic architecture-decision experiment then completed 60/60.
The failure is retained rather than silently discarded.

Default coding instructions sometimes produced fake XML-looking Read/Glob
text even with tools disabled. No file tool was executed. The tested custom
Kioku prompt removed that behavior. Native text deltas can contain plans before
real tool calls, so the adapter must preserve progress/tool/final distinctions
and citation metadata rather than forwarding every text fragment as the answer.

Automatic compaction reduced a 132,887-token context to 39,879 tokens in
6,869ms. An unsupported backoff claim from an earlier assistant answer survived
as a supposed fact. An explicit source correction removed it on the next recall.
Native conversation history and compacted summaries must not become repository
truth without re-grounding.

## Latency and resource observations

| Workload | Median | P95 |
| --- | ---: | ---: |
| Main soak successful native calls | 4.310s | 12.778s |
| Persistent short architecture recalls | 1.225s | — |
| Standalone chat trial calls | 3.155s | 10.308s |
| Real-source fixture questions | 13.280s | 22.923s |
| Latest local Mihari adapter calls | 7.781s | 13.101s |

Haiku fanout 1/2/4 completed in roughly 2.94–3.44 seconds per batch across
three hourly rounds. Sonnet fanout 4 completed in 4.67–4.99 seconds. These are
small synthetic workloads, not production capacity measurements. Sampled peak
sum of POC descendant process RSS was 910.2MiB; shared pages can be counted
multiple times and sampling can miss peaks.

Matching inference configuration matters: the same six backend review-plan
prompts had Haiku median 10.487s by default versus 4.936s with thinking disabled
(verified zero thinking tokens). List-price equivalent totals were $0.045133
and $0.019164 respectively. Sonnet 5.5 median was 2.912s, $0.038738 total.
This is a small controlled sample, not a general model ranking.

## Accounting

Captured native list-price equivalent lower bound: **$4.7325434**. This is not an
actual subscription charge or a proof of financial savings. Cancelled calls may
not report final usage; unaggregated probes and native helper work can be absent.

`total_cost_usd` and `modelUsage` are cumulative across ordinary turns and resume.
A forced worker replacement preserved memory but reset its cost counter.
Four reset boundaries were observed; one overlapping same-session experiment
was excluded as ambiguous. Persist host accounting deltas and reset segments:
neither summing every native total nor taking only a session maximum is safe.

Native /usage snapshots showed shared account window 26%/week 6% at 22:35Z,
then 52%/week 8% at 00:42Z. Usage credits were off. These include other account
activity and lack a pre-POC baseline, so they cannot be attributed exclusively
to this experiment.

## Server phase

The initial expired-login evidence remains in `results/server-summary.json`.
The authenticated follow-up and safe artifacts are documented in
[SERVER_RESULTS.md](SERVER_RESULTS.md). No Mac credentials were transferred;
production containers/routes were not changed.

## Provisional recommendation

For Mihari, favor a fresh session per repository/pass, with existing briefing,
current source, and diff supplied; resume within that job if useful. For chat,
keep Kioku DB history as durable truth. Stateless execution with supplied history
is operationally simple. Stateful resume can reduce repeated context and latency
but needs native session storage, a per-conversation mutex, prompt versioning,
and robust accounting. A persistent process belongs to one active conversation,
not a multi-user routing pool or every historical chat.

Live server execution is now validated. Production integration, operational
limits and account provisioning remain separate decisions; this research does
not authorize a production cutover.

## Reproduction and references

See README and scripts. Safe aggregate artifacts are in `results/`; raw native
events remain outside Git because initialization can contain local metadata.

- https://code.claude.com/docs/en/headless
- https://code.claude.com/docs/en/cli-reference
- https://code.claude.com/docs/en/agent-sdk/cost-tracking
- https://code.claude.com/docs/en/env-vars
- https://code.claude.com/docs/en/memory
