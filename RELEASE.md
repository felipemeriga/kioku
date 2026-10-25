# Automated releases

A successful **CI push run on main** starts Release when repository variable
`KIOKU_RELEASE_ENABLED` is exactly `true`. Unset or `false` keeps production
release preparation disabled, before any version commit, build, or Hive write.
Pull requests cannot release. Explicit owner-only prerelease rehearsals retain
their separate opt-in path.
Release creates a patch version only for affected packages, commits their manifests
and lockfiles, validates that exact commit through CI (and retrieval evaluation
for backend changes), then builds container images on Docker Build Cloud. Native
CLI executables are built and smoke-tested on their target operating systems.

After **all required checks and artifacts succeed**, one commit updates the
corresponding image lines in `felipemeriga/hive`. Docker Compose references contain
both a human-readable version and an immutable digest. Dokploy's existing Hive
GitHub integration deploys those paths; Release does not call a second deploy hook.
Stable GitHub Releases and the completion tag are published only after Dokploy
reports `done` for the exact Hive commit on every affected Compose service.
The manifest records the Hive commit and verified deployment IDs. API errors,
failed/superseded deployments, or timeout leave releases as drafts for retry.
CLI releases additionally contain executables, installers, and SHA256SUMS.

## One-time configuration

Configure these in the Kioku GitHub repository before enabling production releases:

| Setting                                                            | Purpose                                                                                                              |
| ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| `KIOKU_RELEASE_ENABLED` repository variable                         | Production activation gate; keep `false` while merging the application stack, then set to `true` when the full main tree is ready |
| Existing `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` secrets           | Docker Hub and Build Cloud authentication; account must access the builder and push Kioku images                     |
| `HIVE_RELEASE_TOKEN` secret                                        | Fine-grained PAT for **felipemeriga/hive only**, Contents read/write; its commits trigger Dokploy's Hive integration |
| `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` repository variables | Public browser configuration baked into frontend builds; never use a service-role key                                |
| Optional `DOCKER_CLOUD_BUILDER` variable                           | Defaults to `felipemeriga1/builder`                                                                                  |
| Existing `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY` secrets             | Retrieval evaluation gate                                                                                            |
| `DOKPLOY_API_KEY` secret                                           | Read access to Dokploy deployment history for every affected Compose service                                         |
| `DOKPLOY_URL` variable                                             | HTTPS Dokploy origin, without `/api` or another path                                                                 |
| `DOKPLOY_COMPOSE_IDS` variable                                     | JSON mapping `backend`, `worker`, `mcp`, `frontend`, `mihari` to their Compose IDs                                   |
| Optional `DOKPLOY_DEPLOY_TIMEOUT_SECONDS` variable                 | Verification timeout (default 900 seconds, maximum 3600)                                                             |

Repository workflow permissions must permit `GITHUB_TOKEN` contents writes. Main
branch rules must allow the release workflow's ordinary fast-forward version
commit. The workflow **never force-pushes or bypasses branch protection**; if the
repository disallows this, it fails before builds. The version commit is made with
`GITHUB_TOKEN`, whose pushes do not recursively trigger CI. The same release run
explicitly executes CI against that new commit instead.

To merge CD before the application stack safely, set the activation variable to
`false` first. Merge CD and all application changes using merge commits, and wait
for the final main push's CI to pass. Then set the variable to `true` and rerun
that actual push CI run. Its completed `workflow_run` event uses the normal
production release path against the exact merged features; no local replay,
synthetic deployed ledger, or empty test commit is needed. Keep the variable
enabled for subsequent automatic releases. Disabling it blocks new preparation;
it does not cancel an already-running deployment.

In Dokploy, enable Hive auto-deploy and set each Compose service's Watch Paths:
`kioku/backend/**`, `kioku/worker/**`, `kioku/mcp/**`, `kioku/frontend/**`, and the
cloud watcher's actual directory. Check that GitHub delivery works before relying
on unattended deployment. The read-only `deployment.allByCompose` API must return
records whose description is exactly `Commit: <full Hive SHA>` or
`Hash: <full Hive SHA>`. Verification requires the latest deployment for each
affected service to match that commit and reach `done`; old successful deployments
cannot satisfy a new release. The backend image requires both backend and worker
IDs. Use the `mihari` key even during the legacy watcher transition. For example:

```json
{
  "backend": "compose-id",
  "worker": "compose-id",
  "mcp": "compose-id",
  "frontend": "compose-id",
  "mihari": "compose-id"
}
```

Dokploy's `done` status confirms the Compose deployment command completed; it is
not an application-level readiness probe. Runtime health and rollback remain
visible in Dokploy. Never configure an API credential with broader rights than
needed for these read-only deployment-history requests.

The Mihari rename in PR #133 needs a coordinated Hive/Dokploy migration. Before
that migration, the planner recognizes `watcher/Dockerfile` and updates
`kioku/watcher/docker-compose.yml` with `kioku-watcher` images. Once the source is
`mihari/`, Hive must also use `kioku/mihari/docker-compose.yml` and
`felipemeriga1/kioku-mihari`. A mismatch stops promotion instead of rewriting a
service or its data mounts. AWS/KMS, trigger tokens, mounts, and all other Compose
configuration are preserved. Database migrations are **not applied by CD**;
apply required migrations before releasing code that depends on them (including
Manabi's initial schema). CI validates the schema, not production migration state.

## Versions and change detection

Default policy: increment **patch** for each affected package on every main
release. This avoids requiring a second release-PR merge. Intentional major/minor
changes can update the package's manifest before merging; automation then applies
the patch increment. Independent MCP/Mihari versions live in `.release/versions.json`;
frontend/CLI use package.json + package-lock.json, backend uses pyproject + uv.lock.
The CLI's displayed version is kept in sync. No npm publishing token is needed.

- Backend inputs rebuild backend/worker and MCP.
- Frontend inputs rebuild frontend only.
- CLI inputs rebuild the CLI binaries and Mihari, which bundles the CLI.
- Mihari (or legacy watcher) inputs rebuild that image only.
- Shared root Docker inputs rebuild all container images.
- Release machinery changes rebuild every package, exercising the new pipeline.
- Documentation-only changes do not release.

The first release bootstraps all packages so Hive can move from mutable `latest`
tags to digests. Later plans compare against the last successful promotion tag,
so skipped/stale main runs do not lose unreleased changes. Redis is an upstream
image, not a Kioku build/package: pin its upstream version/digest through a reviewed
Hive change. The pipeline does not rebuild Redis or silently upgrade it.

The cross-job image matrix omits the public registry namespace: it may equal
`DOCKERHUB_USERNAME`, and GitHub suppresses outputs containing secret values even
when those values are public account names. Build jobs reconstruct full image
references without passing credential-shaped values through outputs.

Release runs serialize. Stale runs cannot promote after main advances. Retries of
the same release reuse the persisted package plan and existing uniquely tagged
images after validating their OCI revision against the exact release commit;
auth/network errors cannot be mistaken for an absent tag. Failed builds never
update Hive. Failed pushes or deployment verification leave draft releases for
retry. The source branch is rechecked immediately before every Hive push. No `latest` image tag is written. Revert Hive image references to roll
back; do not republish old semantic versions. Keep branch/tag protections compatible
with automated release tags.

## CLI installation

CLI releases build Linux x64/ARM64, macOS Intel/Apple Silicon, and Windows x64.
Bun's runtime is embedded; end users do not install Node, Bun, or npm. Executables
are not yet platform-code-signed/notarized. Unsupported Windows ARM is reported
explicitly. Native runner smoke checks execute version/help/session-start and
standalone hook invocation. When Manabi is present, each native executable also
connects to a loopback WebSocket backend, sends its hello, reconnects after a
forced close, and stops. No OS service is installed by this smoke; full installed
service E2E remains a separate integration check.

Download `install.sh` or `install.ps1` from a published **cli-vVERSION** release,
review it, and run it. Installers discover the latest published CLI release among
the most recent 100 releases, or accept `KIOKU_VERSION=0.4.1` to pin explicitly.
An explicit pin may also name a prerelease, for example
`KIOKU_VERSION=0.4.1-e2e.20261024`; automatic discovery remains stable-only.
They download over HTTPS and verify the executable against the release's SHA256SUMS
before running/installing it. This detects corruption, not a compromised release
publisher. macOS/Linux defaults to `~/.local/bin`; Windows uses the user's local
Programs directory and adds that directory to the user PATH. Set
`KIOKU_INSTALL_DIR` to choose another location. No admin privileges are requested.

## Local validation

```sh
python3 -m unittest discover -s scripts/release -p 'test_*.py' -v
uvx ruff check scripts/release
uvx ruff format --check scripts/release
# Install actionlint, then:
actionlint
cd cli && npm ci && npm test
```

Do not run the prepare/promote commands against production branches as a local
"test": they are release orchestration helpers. Unit tests use temporary fixtures;
the native executable smoke does not install a service or change agent settings.

## Explicit premerge rehearsal

Automatic production release remains main-only. An owner-triggered repository
rehearsal uses the already-registered CI workflow on a dedicated integration
branch that contains the complete tested release tree:

```sh
gh workflow run ci.yml --ref test/release-cd-e2e-20261024 \
  -f release_e2e=true -f rehearsal_id=gha-20261024
```

The manual handler requires the repository owner, an explicit opt-in, a nonempty
run ID, and a `test/release-cd-e2e*` branch. Pull requests and ordinary pushes
cannot enter it. It runs CI first, then calls the same release workflow in
prerelease-only mode; the exact version commit is checked again before builds.
Shared checks live in `checks.yml` to avoid recursive CI/release workflow calls.
The prepare step validates private Hive file-content access, an isolated Git
read with the supplied token, and read access to every Dokploy deployment-history
endpoint before recording a version commit. Repository metadata or its user-level
`permissions.push` field alone do not establish a token's Contents grant. No SSH
fallback is used by the repository workflow.

A brand-new workflow filename cannot be dispatched before GitHub knows it on the
default branch. The existing CI workflow's registered ID permits selecting this
branch's dispatch definition, verified with a real CI-only run before activation.
For explicitly authorized local diagnosis, the same scripts remain available:

```sh
export RELEASE_PRERELEASE=true
export RELEASE_BRANCH=integration/release-e2e
python3 scripts/release/release.py prepare --source "$SOURCE_SHA" \
  --branch "$RELEASE_BRANCH" --rehearsal-id run-20261024 --output /tmp/plan.json
# Commit manifest changes with the standard version-commit subject, push only
# this integration branch, then build/validate artifacts for that exact commit.
# Set RELEASE_SHA, GH_TOKEN and the same deployment settings, then:
python3 scripts/release/promote.py
```

This is a **real Hive promotion/deployment**, not a dry run; use it only when that
rollout is explicitly authorized. The nominated remote branch must still match
`RELEASE_SHA` immediately before every Hive push. Non-main plans require both
`RELEASE_PRERELEASE=true` and a safe rehearsal ID. They publish only
`<package>-v<version>-e2e.<id>` prereleases with `latest=false`, use distinct image
tags, and write `release/rehearsed-*` tags. They never write production completion
tags or affect main's successful-release baseline. Package manifests in the
integration branch carry the bumped base version; GitHub release channel/tag and
image tag identify the rehearsal. Do not merge rehearsal version commits to main.

For credential diagnosis without deployment, the owner can run:

```sh
gh workflow run ci.yml --ref feat/release-cd -f credential_probe=true
```

This checks metadata, actual Contents API access, isolated Git transport, and
Dokploy read access. After successful read checks it creates and deletes only a
unique non-main `kioku-cd-permission-probe-*` branch to verify write capability.
A Hive fine-grained PAT must select `felipemeriga/hive` and grant **Contents: read
and write**; granting only Metadata or Actions is insufficient. No credential
value is printed or written to a file. The probe never invokes deployment.
