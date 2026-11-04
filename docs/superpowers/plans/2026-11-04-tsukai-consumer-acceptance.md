# Tsukai consumer acceptance handoff

Implementation PR: #209. Default execution remains API. Native pilot requires the selected operation in `TSUKAI_NATIVE_TASKS` and exact `TSUKAI_CREDENTIAL_OWNER_ID`; unrelated owners retain API. There is no fallback after a native execution failure.

## Reproducible checks

From the repository root, with the backend environment activated:

```sh
TSUKAI_PROTOCOL_DIR="$PWD/tsukai/protocol" python -m pytest -c backend/pyproject.toml backend/tests/test_tsukai_*.py backend/tests/test_chat_scope.py backend/tests/test_llm.py backend/tests/test_usage_ledger.py backend/tests/test_text_to_sql_scope.py backend/tests/test_citations.py backend/tests/test_contextual.py backend/tests/test_query_cache.py backend/tests/test_rag_stream_budget.py backend/tests/test_briefing_mcp_persistence.py backend/tests/test_usage_routes.py -q
```

The separately owned runtime protocol must be present for the canonical-schema contract test. Standalone consumer branches explicitly skip that dependency test; integration must run it.

The product migrations are validated transactionally against a disposable database. Never run the minimal domain fixture against production:

```sh
cat backend/tests/sql/tsukai_chat_domain_fixture.sql \
  supabase/migrations/20261104130000_tsukai_chat_bridge.sql \
  supabase/migrations/20261104160000_tsukai_native_usage.sql \
  supabase/migrations/20261104170000_tsukai_domain_deletions.sql \
  supabase/migrations/20261104190000_tsukai_pre_admission_privacy.sql \
  supabase/migrations/20261104200000_tsukai_consumption_receipts.sql \
  backend/tests/sql/tsukai_chat_acceptance.sql \
  backend/tests/sql/tsukai_lifecycle_acceptance.sql |
  ssh meriga-server 'docker exec -i kioku-tsukai-fixture-postgres psql -U tsukai_fixture -d kioku_chat_fixture -v ON_ERROR_STOP=1 -q -o /dev/null'
```

This creates no retained fixture data: the script ends with ROLLBACK. It verifies accepted-turn idempotency, changed-payload conflicts, cross-owner rejection, active-conversation exclusion, one assistant publication, citation allocation, parameterized metadata scope, and deletion intents/evidence cleanup including pre-admission orphan sources.

Frontend, from `frontend/`:

```sh
npm run build
VITE_SUPABASE_URL=http://localhost VITE_SUPABASE_ANON_KEY=fixture npm run test:run -- src/lib/chatTransport.test.ts src/lib/api.test.ts src/pages/SettingsPage.test.tsx src/components/ChatArea.test.tsx src/components/ThinkingBar.test.tsx
```

The URL/key above are safe fixture strings, not account credentials.

## Browser seed and expected evidence

Use an isolated staging owner folder `Tsukai acceptance` and upload `tsukai-acceptance.md` with this exact content:

```text
Tsukai acceptance fixture, revision 1.
The haru-writer retries a job at most three times.
After the third failed attempt it places that job on retry_queue.
The fixture marker is HARU-RETRY-THREE.
These statements describe this fixture only, not the real Kioku implementation.
```

A sibling folder should contain a separate filename and a distinct sentinel. A file-scoped chat must never return sibling content through search, graph or metadata. Test cross-owner access with isolated staging identities, while permitting native inference only for the authorized credential owner.

## Active acceptance matrix

Start the user's greater-than-four-hour monotonic ACTIVE integrated-testing window only after the assembled UI/backend/MCP/Mihari/runtime are deployed and ready. Development time and idle waiting do not count. The coordinator owns the clock and evidence collection.

| Surface | Exercise | Required visible/durable result |
|---|---|---|
| UI chat | Haiku and Sonnet, plain/agentic/deep, debug on/off | Incremental text, observable tool progress, final canonical replacement, source citations, saved answer |
| Inspect | Open tools, chunks and execution tabs | Exact query, current Kioku folder breadcrumbs, source IDs/content hashes, bounded preview, paginated exact result, observed attempt/tool timings; no hidden thinking |
| Resumed chat | Follow-up in the same conversation after worker/container replacement | Correct explicit native mapping; current-turn citations only; missing state requests explicit rebuild |
| Admission loss | Drop response after runner acceptance but before backend mapping, then restart backend | Same exact turn/idempotency body replays; one provider start and one assistant message |
| Disconnect | Navigate away/reload while text is arriving | Runner completes and backend reconciles without browser; reconnect cursor deduplicates deltas |
| Cancel/rebuild | Cancel active work, then use explicit rebuild action | Typed terminal uncertainty/cancellation; fresh generation rebuilt only from committed history |
| Concurrency | Distinct conversations, then two distinct turns in one conversation | Independent work within limits; conflicting same-conversation turn rejected |
| Revocation | Remove an accepted turn's captured folder; follow with healthy work | Durable failed scope_revoked, deferred cancellation, released domain lock, no poisoned-batch starvation |
| MCP | Actual initialize/list/call against public service; concurrent long metadata and another read | Fresh direct Tsukai call, responsive service, scope preserved through thread offload |
| MCP identity | Reuse a session ID with another owner's API key or different API-key scope | Rejected before tool/model execution |
| Metadata child | Occupy both root slots and ask scoped counts from a native tool | One fresh depth1 tool-disabled reserved child; no arbitrary SQL, no scope widening/delegation |
| Machine contracts | Inject question, empty result, malformed JSON and needs_input | Bounded typed non-success; no prose/question published as completed data |
| Mihari | Changed fixture HEAD, unchanged HEAD, failed section, retry, stale result | Real briefing write only after validation/CAS; no unnecessary model work for unchanged HEAD; reviewed marker retained on failure |
| Usage admin | Native repaired/failed/completed calls plus API history | Per-job/attempt rows; missing counters stay unknown; native list-equivalent estimate separate from cash/API charges |
| Active sessions admin | Open while two jobs execute; poll several times | Current owner/job/attempt/native session/scope/state/elapsed shown; non-admin rejected server-side |
| Lifecycle | Delete conversation/account while runner unavailable, then restore | Durable cleanup intent survives domain cascade and reaches cleaned; exact artifacts/native state removed |
| Existing UI | Conversations, documents, folders, notes, settings, navigation during generation | No target regressions or cross-conversation streamed-message injection |

After the active test window and all target regressions are resolved, deploy the reviewed images through the repository CI/CD/Dokploy flow. Record exact source/image commits, actual served models/CLI version, test duration and any remaining limitations. Do not claim zero possible bugs.

## Explicit evidence limits

Native CLI MCP transport does not expose its native tool-use ID. The trace reports null with an availability reason, retaining authoritative backend invocation UUID plus turn/job/attempt IDs. No ambiguous name/input matching is presented as a verified native-ID mapping. Full artifact retention is seven days; bounded message debug and citation records follow conversation retention.

Staging must set `KIOKU_NOTION_SCHEDULER_ENABLED=false`; the default is true to preserve production scheduling. This prevents a staging backend from running a duplicate Notion scheduler.
