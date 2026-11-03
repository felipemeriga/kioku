# Native Claude Code local research POC

This branch is an isolated experiment. It does not change Kioku's app, deployment,
billing, or production data. Synthetic fixtures and raw process output live under
`/private/tmp/kioku-claude-poc-runtime`, outside the checkout. Native Claude Code
uses the account's existing sign-in; the adapter removes API/provider environment
fallbacks and never reads, copies, or proxies authentication credentials.

## Experiments

- `soak.py`: at least three real hours of periodic work across three evolving local
  Git repositories. Covers read-only MCP retrieval/graph tools, fresh repository
  maintenance, the real Mihari review dispatcher with an isolated CLI transport,
  explicit session resume, stateless history, parallel sessions, tool failures,
  and process cancellation/restart. The production DB/indexer/network are excluded.
- `duplex.py`: three hours of a persistent native `stream-json` input/output
  conversation with idle gaps, changing architecture decisions, and forced
  process replacement with explicit session resume.
- `extended.py`: context length, JSON schema, same-session concurrency,
  nonpersisted-session behavior, changing repository facts, interruption recovery,
  and custom/default system-prompt overhead.
- `local_mihari.py`: actual Mihari `main` and `process_repo`, local Git
  polling/cloning/fetching, native Claude transport, per-repository sessions,
  unchanged-HEAD no-op gating, injected review failure and next-pass recovery.
  Generated activity/documentation is persisted in the local fixture backend
  and supplied to later passes. Only storage/auth/index-upload services are
  isolated fixture adapters.
- `complex_repo.py`: real read-only Kioku source snapshot questions with
  deterministic source-path validation, tested on Haiku and Sonnet.
- `variants.py`: batched maintenance vs repeated session context over twelve
  actual fixture revisions, structured outputs and source-grounded assertions.
- `resources.py`: process RSS sampling for only POC process descendants, without
  collecting process arguments or credentials.
- `local_chat.py`: standalone localhost SSE adapter testing stateless and
  stateful conversation history, partial text, and answer persistence after
  a browser-like client disconnect. It is not integrated into the Kioku app.
- `report.py`: aggregates metrics and normalizes cumulative native session
  list-cost totals rather than incorrectly adding them once per turn.
- `prompt_parity.py`: runs the actual backend review-plan prompt through the
  native CLI for six change classes on two models, using isolated backend data.
- `concurrency.py`: repeats bounded one/two/four-process workloads at zero,
  one and two hours while the other soaks continue.
- `protocol_cases.py`: explicit probes for stream-input routing, cross-directory
  resume, turn-limit termination and a host-controlled final-answer fallback.
- `compaction.py`: large synthetic research history with a 100k native
  compaction threshold and a resumed current-facts question.
- `fixture_mcp.py`: minimal read-only synthetic MCP source; no production tools.
- `test_native.py`: local process adapter regression tests without model calls.

## Run

Requires Python 3.10+, `requests`, `cryptography`, and the signed-in native `claude`
executable. The actual tests began with Claude Code `2.1.285`. Do not use `--bare`
for this subscription experiment: this version documents that bare mode skips
OAuth and requires API/provider authentication.

```sh
python research/claude_code_poc/soak.py --runtime /tmp/kioku-poc/soak --duration 10800
python research/claude_code_poc/duplex.py --runtime /tmp/kioku-poc/duplex --duration 10800
python research/claude_code_poc/extended.py
python research/claude_code_poc/local_mihari.py
python research/claude_code_poc/complex_repo.py
python research/claude_code_poc/variants.py
python research/claude_code_poc/variants.py --strict --revisions 4
python research/claude_code_poc/local_chat.py
python research/claude_code_poc/prompt_parity.py --thinking-off
python research/claude_code_poc/compaction.py
python research/claude_code_poc/report.py
cd research/claude_code_poc && python -m unittest test_native.py
```

Checkpoints record real monotonic elapsed time, UTC start/finish, checks, call IDs,
and failures. A successful native `result` frame reports a **list-price equivalent**,
not the actual subscription charge. Raw output must not be uploaded without
review: initialization events can contain local account/configuration metadata.

Official references used for the invocation contract:
- https://code.claude.com/docs/en/headless
- https://code.claude.com/docs/en/cli-reference

Research is ongoing; no three-hour result is claimed until both active soak
checkpoints show `completed` and elapsed time of at least 10,800 seconds.

The first dispatcher run exposed prose appended to requested JSON. The test
preserves that failure and switches the review-plan adapter to native
`--json-schema`. `--resume-run` resumes the experiment checkpoint without
resetting its monotonic elapsed timer. A persistent duplex trial also exposed
a false model refusal of an artificial token-recall prompt; its raw evidence
is retained separately while the continuing trial uses realistic architecture
decisions. `total_cost_usd` is cumulative over a session, including explicit
resume across processes; `usage` is per turn. Cancellation can leave usage
unreported. These figures do not measure the remaining subscription allowance.
