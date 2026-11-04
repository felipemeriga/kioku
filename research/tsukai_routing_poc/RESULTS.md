# Tsukai routing POC: matched API/native execution

Research only. This POC ran on `meriga-server` on 2026-11-04 and made no production application, database, conversation, briefing or billing-route changes. Temporary services stopped after testing. API calls used the existing backend container environment through a private `docker exec` stdin worker; the key was never extracted. Its temporary script was removed. Native execution used the already signed-in server Claude CLI.

## Answer

The extra backend HTTP hop was negligible in this test: about **1ms**. Fresh native CLI execution was **1.3–1.6s slower** than API execution for these tiny supplied-evidence tasks. That difference cannot be blamed on the backend hop. This does not establish performance for long production RAG conversations.

A real Chrome page submitted to the fixture backend, which streamed through the separate Tsukai service; both API and native results rendered incrementally. Actual MCP JSON-RPC and an actual Mihari fixture dispatcher also reached Tsukai directly.

## Topology actually tested

- Browser → loopback backend HTTP/SSE service18782 → Tsukai HTTP/SSE service18781 → native CLI or API worker.
- Mihari-shaped caller → Tsukai directly. Additional real Mihari `main/process_repo` fixture used real Git polling/cloning/review scheduling and an injected transport adapter to this same direct Tsukai endpoint.
- JSON-RPC stdio MCP client → MCP `initialize`, `tools/list`, `tools/call` → Tsukai directly. MCP exposes a bounded synthetic knowledge question; no backend job hop.
- Native harness → a separate read-only fixture MCP source-search tool. API harness smoke executes an equivalent synthetic source tool through its own two-round loop.

These are isolated POC services and a small browser page, **not the production React UI or FastAPI application routes**. No Supabase/KMS, production graph, Voyage retrieval or embedding quality is benchmarked. The HMAC fixture grant binds caller/owner/expiry and rejects mismatched owners, but service role header labels and the UI fixture identity are test scaffolding, not production authentication. No durable queue, durable event replay, distributed leases, production citation registry or full Inspect UI was implemented.

## Matched comparison method

Five randomized/interleaved repetitions for each of three paths × two engines =30 model executions. Five additional API direct controls. Native CLI version was2.1.318. Model requested and served: **claude-haiku-4-5-20251001**. Same task user prompt and custom system prompt per path. No tools in the timed completion benchmark. API extended thinking was not enabled; native used `MAX_THINKING_TOKENS=0`, low effort, hooks/project instructions disabled, no MCP tools. Native calls were fresh subprocesses with native session persistence disabled; API calls each created a new independent message list through one persistent SDK process. SDK client retries were disabled. API max_tokens512; native has no equivalent enforced cap in this adapter, so prompts request short answers and observed output lengths are recorded.

The native harness still adds its own scaffold: median input totals were580tokens(native) versus93(API) for chat, and598 versus111 for maintenance. Thus these are matched external prompts/model/settings, **not identical underlying provider payloads**. Typical chat output medians were78 versus75tokens. Native process startup and its wrapper are part of the intended execution path and cannot be eliminated from these results.

Timings use client monotonic clocks. Mock no-model tests isolate routing from stochastic model latency. p95 below uses nearest-rank; with only five samples it equals the maximum and is not a production percentile/SLA. The direct control is a separate batch, not enough to interpret submillisecond API median differences causally.

| Path | Engine | n | Median first text | Median completion | Sample p95 completion |
|---|---|---:|---:|---:|---:|
| Backend → Tsukai chat | API | 5 |0.535s|1.247s|1.592s|
| Backend → Tsukai chat | Native |5|1.629s|2.854s|3.315s|
| Direct Mihari → Tsukai | API |5|0.547s|0.791s|0.865s|
| Direct Mihari → Tsukai | Native |5|1.280s|2.089s|2.328s|
| MCP stdio → Tsukai | API |5|Not exposed by normal MCP tool result|0.937s|1.131s|
| MCP stdio → Tsukai | Native |5|Not exposed by normal MCP tool result|2.252s|2.545s|
| Direct API worker control, chat prompt |API|5|0.524s|1.251s|3.027s|

All30timed routed executions returned a successful transport terminal result. All10Mihari timed free-text outputs contained the correct JSON payload but wrapped it in Markdown fences, so strict `json.loads` without fence removal rejects10/10; this timing benchmark did not enforce structured-output schema. Existing API maintenance strips fences, whereas the actual native Mihari review-plan smoke exercised `--json-schema`. Treat these as distinct contracts, not proof of strict-output parity. The20chat/MCP answers contained the expected retry limit and identifier, without proving every additional statement correct. The five direct API controls also succeeded. The first native call (Mihari) completed2.328s versus2.089s median repeated calls; first routed API Mihari0.865s versus0.791s median. Every native request still starts a new process. These first-versus-later observations are not a controlled cold-cache benchmark. The new direct API worker's first call was3.027s, so the control includes a startup outlier; it is not silently discarded.

## Hop overhead independent of the model

Ten no-model responses per path:

| Route | Median total |
|---|---:|
| Backend → Tsukai |2.35ms|
| Caller → Tsukai directly |1.34ms|
| Fresh stdio MCP process → Tsukai |92.22ms|

MCP's92ms includes launching/importing a new Python MCP process for each sample. A persistent MCP server would not repeatedly pay that cost. The difference between the two HTTP routes was approximately1.01ms. Do not compare that directly to native/API model latency variability.

## Real browser rendering and functional coverage

Chrome/Playwright connected through a local SSH tunnel to the server fixture UI. In one browser sample per engine:

| Engine | First rendered text | Terminal event rendered | Observed SSE events |
|---|---:|---:|---:|
| API |638ms|1242ms|25|
| Native |1157ms|2701ms|35|

The screenshot and `results/browser.json` preserve evidence. These measurements include the Mac↔server connection; the server benchmark table does not. The page's terminal event and stream-close/run bookkeeping were initially sampled in the wrong order by the browser test; the test was corrected to wait for a completed run record. Failed sampling output is not included as successful browser evidence.

Additional checks:

- API tool harness and native tool harness each executed source search and answered the synthetic retry question; tool events were observable. This is a functional smoke, not a fair latency comparison of full production harnesses.
- Stateful native conversation resumed and recalled PostgreSQL outbox and `event_id` correctly through Tsukai.
- A correctly signed grant for a different owner was rejected403 before model execution. Three scope unit tests cover owner tampering, caller mismatch and expiry.
-23recorded non-chat native executions had23distinct session IDs, including all actual Mihari model calls; the injected adapter deliberately ignores the old fixture's resume argument.
- Actual Mihari dispatcher: three synthetic Git repositories; all7boolean checks passed, including changed source, unchanged-HEAD no model work, injected pre-inference failure retaining SHA, retry recovery and detailed docs updated to current retry count. Database/KMS/index uploads were fixture adapters. Its original transport expected backend REST; the injected adapter translates those fixture requests into direct Tsukai submissions rather than introducing a real backend hop.
- Client disconnect after first SSE event still produced a successful551-character answer in the server request record. Health during generation returned200in1.16ms. This is generation persistence within the running process; durable replay across process/container loss is **not implemented** here.

## Quality and accounting limitations

Successful terminal execution is not proof of factual correctness. Some responses inferred that a retry limit means a particular failed state or event rejection mechanism; supplied evidence did not establish those details. Native also added a Markdown heading despite the short-answer request. None of these tests establish production RAG/citation parity. The comparison uses tiny tasks intentionally to make routing overhead visible.

`results/benchmarks.jsonl` contains safe synthetic outputs, actual model/usage counters and timing; native totals remain explicitly list-price equivalents, not subscription cash spending. Native cumulative costs are not summed across resumed sessions. API tool smoke stores final-round usage only, so it must not be used as a total-cost report. No cost-saving conclusion is inferred from this timing test.

## Recommendation

The agreed direct MCP/Mihari routes are viable in the POC. Keep UI→backend→Tsukai because the extra internal hop measured about1ms and preserves product authorization/conversation ownership. Do not optimize it away based on model latency. Expect fresh native CLI completions to add around1–2seconds on small jobs in this environment; longer jobs need matched production-task comparisons. Stateful chat may amortize context, but no large resumed-chat timing benchmark was performed in this POC.

Next implementation gates remain the spec's durable job/event/session layer, real Kioku scoped retrieval/debug provenance, proper service authentication, cancellation/reconciliation, quota/auth recovery and production rollout authorization. This branch remains research-only and should not be merged as application code.
