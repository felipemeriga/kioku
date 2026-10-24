# Automated releases

A successful **CI push run on main** starts Release. Pull requests cannot release.
Release creates a patch version only for affected packages, commits their manifests
and lockfiles, validates that exact commit through CI (and retrieval evaluation
for backend changes), then builds container images on Docker Build Cloud. Native
CLI executables are built and smoke-tested on their target operating systems.

After **all required checks and artifacts succeed**, one commit updates the
corresponding image lines in `felipemeriga/hive`. Docker Compose references contain
both a human-readable version and an immutable digest. Dokploy's existing Hive
GitHub integration deploys those paths; Release does not call a second deploy hook.
A GitHub Release per changed package contains the source/version/image manifest.
CLI releases additionally contain executables, installers, and SHA256SUMS.

## One-time configuration

Configure these in the Kioku GitHub repository before enabling production releases:

| Setting                                                            | Purpose                                                                                                              |
| ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| Existing `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` secrets           | Docker Hub and Build Cloud authentication; account must access the builder and push Kioku images                     |
| `HIVE_RELEASE_TOKEN` secret                                        | Fine-grained PAT for **felipemeriga/hive only**, Contents read/write; its commits trigger Dokploy's Hive integration |
| `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` repository variables | Public browser configuration baked into frontend builds; never use a service-role key                                |
| Optional `DOCKER_CLOUD_BUILDER` variable                           | Defaults to `felipemeriga1/builder`                                                                                  |
| Existing `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY` secrets             | Retrieval evaluation gate                                                                                            |

Repository workflow permissions must permit `GITHUB_TOKEN` contents writes. Main
branch rules must allow the release workflow's ordinary fast-forward version
commit. The workflow **never force-pushes or bypasses branch protection**; if the
repository disallows this, it fails before builds. The version commit is made with
`GITHUB_TOKEN`, whose pushes do not recursively trigger CI. The same release run
explicitly executes CI against that new commit instead.

In Dokploy, enable Hive auto-deploy and set each Compose service's Watch Paths:
`kioku/backend/**`, `kioku/worker/**`, `kioku/mcp/**`, `kioku/frontend/**`, and the
cloud watcher's actual directory. Check that GitHub delivery works before relying
on unattended deployment. A successful Hive push is **promotion**, not proof of
runtime health; deployment progress and rollback remain visible in Dokploy.

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

Release runs serialize. Stale runs cannot promote after main advances. Retries of
the same release reuse the persisted package plan and existing uniquely tagged
images; failed builds never update Hive. Failed Hive pushes leave draft releases
for retry. No `latest` image tag is written. Revert Hive image references to roll
back; do not republish old semantic versions. Keep branch/tag protections compatible
with automated release tags.

## CLI installation

CLI releases build Linux x64/ARM64, macOS Intel/Apple Silicon, and Windows x64.
Bun's runtime is embedded; end users do not install Node, Bun, or npm. Executables
are not yet platform-code-signed/notarized. Unsupported Windows ARM is reported
explicitly. Native runner smoke checks execute version/help/session-start and
standalone hook invocation. Once Manabi is merged, its invalid-config entry smoke
also runs; full installed-service E2E remains a separate integration check.

Download `install.sh` or `install.ps1` from a published **cli-vVERSION** release,
review it, and run it. Installers discover the latest published CLI release among
the most recent 100 releases, or accept `KIOKU_VERSION=0.4.1` to pin explicitly.
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
