# Authenticated server POC

The follow-up **passes live model execution** after the operator completed native
Claude login on meriga-server. The earlier expired-login failure remains recorded
in `results/server-summary.json`; it was not a transport or application outage.
No production app routes, billing, repository data, or deployed app containers
were changed. No Mac credentials were transferred or credential contents read.

## Executed coverage

| Environment | Evidence |
| --- | --- |
| Host, existing native CLI 2.1.207 | 6/6 checks: stateful/stateless chat, MCP maintenance, changed source, concurrent isolation, cancellation/recovery |
| Nonroot container using existing backend image, CLI 2.1.207 | Same 6/6 checks, 512MiB/1CPU, read-only rootfs |
| Actual Mihari main/process_repo on server | 7/7 boolean assertions: 3 local Git repos, isolated sessions, unchanged-head no-op, retained SHA on injected failure, retry recovery, fresh next-pass session, current detailed docs |
| Credential-free client container to host Unix broker | Real partial stream events, stateful/stateless recall, source maintenance, same-session lock and responsive liveness checks |
| Dedicated pinned runner image, CLI 2.1.285 | Built successfully on server, native subscription requests and MCP tools run as UID1000, 1GiB/2CPU, read-only rootfs, private state mount |
| Full runner-container recreation | Same conversation resumed with adopted PostgreSQL/event_id facts in 2.62s |
| Authentication readiness | Actual tiny model probe succeeds; separate empty auth directory produces reauth_required without altering real login |

The recorded follow-up suites contain48native calls:46successful and2deliberate
cancellations, plus separate readiness/diagnostic probes.

Mihari used real Git polling/clone/fetch and its real dispatcher. Supabase/KMS,
index uploads and production backend requests were replaced with local adapters.
There was no production graph/embedding generation. Initial three-repo pass took
55.24s; unchanged-head pass made no model calls; recovery pass took18.75s.

The older CLI failed to resume when the recreated worker used a different cwd.
Keeping `/runtime/calls` stable recovered the stored session in3.37s. The newer
runner also recovered after full container replacement using stable `/data/calls`.
Persist both native state and a stable job/conversation workspace mapping.

Host successful-call median was3.56s; constrained old-container median6.84s.
These are small, differently constrained samples, not a clean transport benchmark.
The host broker delivered first text in2.59s, resumed answers in2.05s, and source
maintenance in5.38s. Liveness during generation responded in1.10ms; a conflicting
same-session turn was rejected in0.52ms. The dedicated image sampled108.8MiB
while a native request was active and about14MiB idle; these are observations,
not measured absolute memory peaks.

## Prompt quality remains separate from transport

One Haiku stateless answer inside the new runner ignored supplied conversation
history and asked for repository access. This failure is retained in the
before-fix artifact. The shared system prompt was ambiguous about when source
verification was necessary. The follow-up explicitly distinguishes supplied
conversation decisions from implementation claims requiring retrieved source.
The retest recalled both values, but added unnecessary questions about unspecified
implementation details. One maintenance answer also overinterpreted missing
deployment evidence as no active deployment; that conclusion is unverified.
Stateful answers were more direct in this sample. Do not
interpret successful transport, valid JSON, or substring checks as proof that
every answer is correct.

## Unattended authentication

The POC delegates renewal of native `/login` credentials to Claude Code; no
custom OAuth refresh client is needed. A rejected refresh requires a new official browser
sign-in. On Linux the CLI stores credentials with mode0600; `CLAUDE_CONFIG_DIR`
selects their directory. Current docs provide expiry warnings, but the old server
CLI predates some status diagnostics. Google is the identity provider during the
browser flow, not a password Kioku should store. See [authentication](https://code.claude.com/docs/en/authentication)
and [expired-login errors](https://code.claude.com/docs/en/errors#login-expired).

A supported alternative for unattended scripts is `claude setup-token`: the
operator authorizes once in the browser, then stores the resulting **one-year
subscription token** as `CLAUDE_CODE_OAUTH_TOKEN` in deployment secret storage.
It is still revocable and needs rotation. Local MCP works; bare mode does not
read it. We verified the command's help, but deliberately did not generate or
capture a token. This option reduces repeated interactive sign-ins; it does not
promise permanent silent Google reauthentication. [Official setup-token documentation](https://code.claude.com/docs/en/authentication#generate-a-long-lived-token).

The tests prove login recovery and persistence through subprocess/container
replacement. They **do not** prove an actual access-token-expiry/automatic-refresh
cycle: we did not read expiry fields, mutate credentials or wait for expiration.

Proposed operational policy, not application implementation:

1. Separate cheap process liveness from model readiness. Use existing request
   results plus one cached tiny-model probe at startup/after recovery; avoid a
   paid model healthcheck every30seconds. `auth_health.py` emits sanitized states.
2. On terminal auth failure, mark the runner unavailable, alert the operator once,
   and retain queued Mihari jobs without advancing their reviewed commit. Show
   an immediate chat error and retain the request instead of hanging.
3. Retry refresh contention/network errors with bounded jitter; do not restart
   repeatedly or fan out login attempts. Official errors distinguish another
   CLI process refreshing from terminal expired credentials.
4. Reauthenticate in the same native state volume, run the model probe, then
   resume queued jobs. No automated Google password/browser operation.
5. API fallback can be an explicit admin-configured option with separate billing
   attribution and a limit. It is absent from this POC and must never happen
   silently. Plan expiry/rotation alerts for a long-lived token too.

## Dokploy-friendly example

Prefer a **separate runner container**, independently bounded from interactive
API workers, with its own private native-state volume and job/socket volume.
This fits Dokploy Compose management without depending on a host-installed CLI.
The host Unix broker remains a viable alternative but adds host service/user
management. Neither architecture is integrated into Kioku by this branch.

`Dockerfile.runner` builds the native binary from the official installer at a
pinned version. `compose.runner.yaml` validates with `docker compose config` and
has no public port, uses UID1000, persistent volumes and resource limits. Its
healthcheck checks only broker liveness. The actual image was built and run on
meriga-server. The POC temporarily mounted the existing **server** native state
for native CLI consumption; a rollout should instead initialize the dedicated
private volume through the official login flow, not copy personal credentials.

```sh
# Run from research/claude_code_poc. Example only; not deployed to the app.
docker compose -f compose.runner.yaml up -d --build
# One official interactive login in the persistent runner volume:
docker compose -f compose.runner.yaml exec native-runner claude auth login --claudeai
# Actual model readiness, separate from process health:
docker compose -f compose.runner.yaml exec native-runner \
  python /poc/auth_health.py --runtime /data/readiness
```

Keep state private to the runner UID; the image creates directories with0700.
Credentials are never baked into the image. Mount state writable so the native
CLI can refresh/save its own credentials. Persist native project transcripts
for stateful resume, and serialize each native conversation in the host adapter.
The fixture broker is research code, not an authenticated multi-user gateway.

All temporary brokers/containers are stopped after testing. Images, fixture
sources and private research logs remain available for reproduction. This PR
remains draft and must not be merged or deployed as an application change.
