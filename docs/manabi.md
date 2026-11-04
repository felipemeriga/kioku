# Manabi machine presence

`kioku init` also installs and starts one background Manabi
process for the current OS user. Subsequent repositories reuse it; no separate
start command is required. It maintains an authenticated outbound WebSocket to
the configured backend, sends heartbeats, and retries disconnected connections
indefinitely with exponential backoff and jitter (up to 60 seconds). Check
machine presence in **Remotes**. Each init also records the repository path and its
configured Claude Code/Codex providers in a local registry. Manabi syncs that current
inventory separately from document indexing. Re-initializing with another provider
keeps both configurations. This does not detect running agents or collect memories.

Existing bindings can be discovered from Claude's project index or Codex's configured
project paths, only when explicit Kioku markers exist and the current account owns
the repository folder. Manabi never crawls the disk or reads session transcripts.
Run init in an older project if it does not appear. Remotes shows OS logos, a friendly
computer name, and an optional name override that survives future init runs.

Missing paths and unreadable registries produce timestamped warnings. A corrupt
registry retains the server's last successful inventory; warnings clear after recovery.
Offline machines show last-known reports. `kioku status` also shows the last local
connection/startup report, including failures that cannot reach the backend.

Startup uses a macOS LaunchAgent, a Linux systemd user service, or a Windows
per-user login task with a periodic restart watchdog. These are **login services**,
not privileged boot services. Linux needs a working systemd user session; running
before login/after logout requires separately configured user lingering. macOS
installation requires a GUI login domain. Installation failures fail init with
an actionable error; re-running init repairs setup. Closing the terminal does
not stop Manabi, but sleep, shutdown, or logout can. It reconnects on return.

Manabi keeps its credential and a small runtime snapshot under
`~/.config/kioku/manabi` (or `$XDG_CONFIG_HOME/kioku/manabi`). It uses the current
Node executable through a stable absolute PATH link when available (for example,
Homebrew’s `bin/node` link), so replacing that Node version does not strand the
service on a deleted Cellar path. Keep Node installed; re-run init after moving
or removing the installation entirely. Standalone release builds
snapshot the Kioku executable instead and require no separate Node runtime. `kioku logout` clears the connection
credential; the supervised process idles until the next init. Machine credentials
only authorize presence and owned-repository inventory updates, not document or memory access.

Heartbeat timeouts use a monotonic clock. Suspension or a substantial wall-clock
change discards the old connection and reconnects. `status.json` holds the latest
local report; `diagnostics.json` keeps only the last 50 status transitions, with
codes and timestamps, without secrets or unbounded log growth. Storage failures
do not stop retries. Credential rejection retries at the capped interval, but
requires `kioku init` to repair registration. No process can connect while the
machine is asleep, shut down, or offline. An explicitly stopped/disabled OS service
stays under user control; Manabi does not reinstall itself or bypass that choice.
On Windows, disable or unregister the scheduled task to stop it deliberately;
ending its process alone is treated as a crash by the periodic watchdog.


See [CLI setup](../cli/README.md), [architecture](architecture.md), and
[operations](operations.md). This service is distinct from agent journal capture.
