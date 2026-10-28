import { useState, type CSSProperties } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  TextField,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DesktopWindowsOutlinedIcon from "@mui/icons-material/DesktopWindowsOutlined";
import { brand, fonts } from "../theme";
import appleLogo from "../assets/os/apple.svg";
import linuxLogo from "../assets/os/linux.svg";
import windowsLogo from "../assets/os/windows.svg";
import {
  getRemoteMachines,
  renameRemoteMachine,
  type RemoteMachine,
} from "../lib/api";
import "./RemotesPage.css";

const colors = {
  "--remote-line": brand.line,
  "--remote-muted": brand.muted,
  "--remote-text": brand.text,
  "--remote-surface": brand.surface,
  "--remote-sunken": brand.surface2,
  "--remote-cyan": brand.cyan,
  "--remote-amber": brand.amber,
  "--remote-green": brand.green,
  "--remote-mono": fonts.mono,
} as CSSProperties;
function date(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Not connected yet";
}

function OperatingSystem({ machine }: { machine: RemoteMachine }) {
  const id =
    machine.os_id ??
    (machine.platform.startsWith("darwin")
      ? "macos"
      : machine.platform.startsWith("win32")
        ? "windows"
        : machine.platform.startsWith("linux")
          ? "linux"
          : "unknown");
  const label =
    machine.os_name ??
    (id === "macos"
      ? "macOS"
      : id === "windows"
        ? "Windows"
        : id === "linux"
          ? "Linux"
          : machine.platform);
  const logo =
    id === "macos"
      ? appleLogo
      : id === "windows"
        ? windowsLogo
        : ["linux", "ubuntu"].includes(id)
          ? linuxLogo
          : undefined;
  return (
    <span className="remote-os">
      {logo && <img src={logo} alt="" aria-hidden="true" />}
      <span>{label}</span>
      <span className="remote-architecture">
        {machine.architecture ?? machine.platform.split("-").slice(1).join("-")}
      </span>
    </span>
  );
}
const warningText: Record<string, string> = {
  repo_unavailable:
    "A registered repository path is unavailable. Reconnect its disk or run kioku init from its new location.",
  registry_unreadable:
    "Manabi cannot read its local repository registry. The last successful inventory is retained; check kioku status on this machine.",
  folder_unavailable:
    "A repository binding is no longer accessible to this account. Run kioku init in that repository to reconnect it.",
  inventory_rejected:
    "The inventory report was rejected. Update Kioku CLI and run kioku init again.",
};

export default function RemotesPage() {
  const cache = useQueryClient();
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameId, setRenameId] = useState<string>();
  const [newName, setNewName] = useState("");
  const rename = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string | null }) =>
      renameRemoteMachine(id, name),
    onSuccess: () => {
      setRenameOpen(false);
      void cache.invalidateQueries({ queryKey: ["remote-machines"] });
    },
  });
  const [selectedId, setSelectedId] = useState<string>();
  const [query, setQuery] = useState("");
  const [connectOpen, setConnectOpen] = useState(false);
  const machines = useQuery({
    queryKey: ["remote-machines"],
    queryFn: async () => await getRemoteMachines(),
    refetchInterval: 15_000,
    throwOnError: false,
  });
  const all = machines.data ?? [];
  const presence = (machine: RemoteMachine) =>
    machines.isError ? "Unknown" : machine.online ? "Online" : "Offline";
  const matches = all.filter((machine) =>
    `${machine.name} ${machine.platform}`
      .toLowerCase()
      .includes(query.trim().toLowerCase()),
  );
  const selected =
    matches.find((machine) => machine.id === selectedId) ?? matches[0];
  return (
    <section data-testid="remotes-page" className="remotes-page" style={colors}>
      <header className="remotes-heading">
        <div>
          <h1>Remotes</h1>
          <p>Your machines and the projects they’re connected to.</p>
        </div>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setConnectOpen(true)}
        >
          Connect machine
        </Button>
      </header>
      {machines.isError && (
        <Alert
          severity="error"
          action={
            <Button onClick={() => void machines.refetch()}>Retry</Button>
          }
        >
          Could not load your machines. {machines.error.message}
        </Alert>
      )}
      <div className="remotes-fleet">
        {machines.isPending ? (
          <span role="status" className="remotes-loading-label">
            <CircularProgress size={15} color="inherit" /> Loading machine
            status…
          </span>
        ) : machines.isError ? (
          <span>
            <i className="remote-dot offline" />
            Status unavailable
          </span>
        ) : (
          <>
            <span>
              <i className="remote-dot" />
              {all.filter((machine) => machine.online).length} online
            </span>
            <span>
              <i className="remote-dot offline" />
              {all.filter((machine) => !machine.online).length} offline
            </span>
            {all.some((machine) => (machine.warnings?.length ?? 0) > 0) && (
              <span className="remotes-attention">
                {
                  all.filter((machine) => (machine.warnings?.length ?? 0) > 0)
                    .length
                }{" "}
                needs attention
              </span>
            )}
          </>
        )}
        <span>
          {machines.isPending
            ? "Loading machines…"
            : machines.isError && all.length === 0
              ? "Machine list unavailable"
              : `${all.length} ${all.length === 1 ? "machine" : "machines"}`}
        </span>
      </div>
      <div className="remotes-workspace">
        <aside className="remotes-machines" aria-label="Machines">
          <TextField
            fullWidth
            size="small"
            placeholder="Find a machine…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            slotProps={{ htmlInput: { "aria-label": "Find a machine" } }}
          />
          <div className="remotes-machine-list">
            {machines.isPending && (
              <div
                role="status"
                className="remotes-machine-loading"
                aria-label="Loading machines"
              >
                {[0, 1, 2].map((index) => (
                  <div
                    className="remote-machine-skeleton"
                    key={index}
                    aria-hidden="true"
                  >
                    <span />
                    <span />
                    <span />
                  </div>
                ))}
              </div>
            )}
            {matches.map((machine) => (
              <button
                key={machine.id}
                className="remote-machine"
                aria-pressed={selected?.id === machine.id}
                onClick={() => setSelectedId(machine.id)}
              >
                <span className="remote-machine-name">{machine.name}</span>
                <span className="remote-machine-meta">
                  <OperatingSystem machine={machine} />
                </span>
                <span className="remote-machine-footer">
                  <span>
                    <i
                      className={`remote-dot ${
                        presence(machine) === "Online" ? "" : "offline"
                      }`}
                    />
                    {presence(machine)}
                  </span>
                  <span>
                    {(machine.warnings?.length ?? 0) > 0
                      ? `${machine.warnings!.length} ${
                          machine.warnings!.length === 1
                            ? "warning"
                            : "warnings"
                        }`
                      : `Manabi ${machine.version}`}
                  </span>
                </span>
              </button>
            ))}
          </div>
          {!machines.isPending && matches.length === 0 && (
            <p className="remotes-empty">
              {machines.isError
                ? "Machine list unavailable."
                : query
                  ? `No machines match “${query}”.`
                  : "No machines connected yet."}
            </p>
          )}
          <p className="remotes-machine-help">
            Run <code>kioku init</code> in a repository to install and connect
            Manabi automatically.
          </p>
        </aside>
        {selected ? (
          <section
            className="remote-detail"
            aria-labelledby="remote-machine-title"
          >
            <header className="remote-detail-heading">
              <div className="remote-detail-identity">
                <span className="remote-machine-icon">
                  <DesktopWindowsOutlinedIcon />
                </span>
                <div>
                  <h2 id="remote-machine-title">{selected.name}</h2>
                  <p>
                    <OperatingSystem machine={selected} /> · Manabi{" "}
                    {selected.version}
                  </p>
                </div>
              </div>
              <Button
                variant="outlined"
                onClick={() => {
                  setRenameId(selected.id);
                  setNewName(selected.custom_name ?? selected.name);
                  rename.reset();
                  setRenameOpen(true);
                }}
              >
                Rename
              </Button>
            </header>
            <div className="remote-statusbar">
              <span>
                <i
                  className={`remote-dot ${
                    presence(selected) === "Online" ? "" : "offline"
                  }`}
                />
                <strong>{presence(selected)}</strong>
              </span>
              <span>Last seen {date(selected.last_seen)}</span>
            </div>
            {(selected.warnings ?? []).length > 0 && (
              <div
                className="remote-warnings"
                aria-label="Last reported warnings"
              >
                {selected.warnings!.map((warning) => (
                  <Alert severity="warning" key={warning.code}>
                    {warningText[warning.code] ??
                      "Manabi reported a sync warning. Check kioku status on this machine."}
                    <span className="remote-warning-date">
                      Observed {date(warning.observed_at)}
                      {!selected.online
                        ? " · Last known report; machine is offline"
                        : ""}
                    </span>
                  </Alert>
                ))}
              </div>
            )}
            <div className="remote-section-title">
              <h3>
                Repositories <span>{selected.inventory?.length ?? 0}</span>
              </h3>
              <span>
                {selected.inventory_updated_at
                  ? `Inventory received ${date(selected.inventory_updated_at)}`
                  : "Not reported yet"}
              </span>
            </div>
            {selected.inventory == null ? (
              <p className="remote-footnote">
                Update Kioku CLI and run kioku init on this machine to report
                its configured repositories. Existing projects are discovered
                only from known provider project indexes with Kioku binding
                markers.
              </p>
            ) : selected.inventory.length === 0 ? (
              <p className="remote-footnote">
                No initialized repositories reported.
              </p>
            ) : (
              <div className="remote-repos">
                {selected.inventory.map((repo) => (
                  <div className="remote-repo" key={repo.id}>
                    <div className="remote-repo-identity">
                      <Link
                        to={`/documents?folder=${encodeURIComponent(
                          repo.folder_id,
                        )}`}
                      >
                        {repo.name}
                      </Link>
                      <div className="remote-repo-path">{repo.path}</div>
                    </div>
                    <div className="remote-agent-tags">
                      {repo.agents.map((agent) => (
                        <span key={agent}>
                          {agent === "claude" ? "✳ Claude Code" : "›_ Codex"}
                        </span>
                      ))}
                    </div>
                    <span
                      className={`remote-repo-status${
                        repo.available ? "" : " unavailable"
                      }`}
                    >
                      {repo.available ? "" : "Path unavailable"}
                    </span>
                  </div>
                ))}
              </div>
            )}
            <p
              className="remote-footnote"
              title="Providers listed here are repository configurations, not detected running processes or open sessions."
            >
              Configured providers · activity detection is not enabled.
            </p>
            <div className="remote-section-title">
              <h3>Connection</h3>
              <span>Authenticated outbound WebSocket</span>
            </div>
            <dl className="remote-connection">
              <div>
                <dt>Registered</dt>
                <dd>{date(selected.created_at)}</dd>
              </div>
              <div>
                <dt>Last connected</dt>
                <dd>{date(selected.connected_at)}</dd>
              </div>
            </dl>
            {!selected.online && !machines.isError && (
              <div className="remote-offline">
                <h3>This machine is offline</h3>
                <p>
                  Manabi reconnects automatically when the machine is awake, its
                  user service is running, and the backend is reachable.
                </p>
              </div>
            )}
            <p className="remote-footnote remote-capability-note">
              Memory collection is not enabled. Manabi reports its connection
              and configured repositories; it does not read memories, inspect
              open sessions, or run remote commands.
            </p>
          </section>
        ) : (
          <div className="remote-detail remotes-empty">
            {machines.isPending && (
              <CircularProgress
                size={24}
                color="secondary"
                aria-label="Loading machine details"
              />
            )}
            <h2>
              {machines.isPending
                ? "Loading machines…"
                : machines.isError
                  ? "Machines unavailable"
                  : query
                    ? "No matching machines"
                    : "Connect your first machine"}
            </h2>
            <p>
              {machines.isPending ? (
                "Your connected machines will appear here."
              ) : machines.isError ? (
                "Retry when Kioku is reachable. Manabi keeps reconnecting automatically."
              ) : query ? (
                "Clear your search to see connected machines."
              ) : (
                <>
                  Run <code>kioku init</code> on that computer. No separate
                  Manabi command is needed.
                </>
              )}
            </p>
          </div>
        )}
      </div>
      <footer className="remotes-footer">
        Presence refreshes every 15 seconds. Machines are marked offline when
        their connection closes or heartbeats expire.
      </footer>
      <Dialog
        open={renameOpen}
        onClose={() => !rename.isPending && setRenameOpen(false)}
        maxWidth="xs"
        fullWidth
        aria-labelledby="rename-machine-title"
        aria-describedby="rename-machine-description"
      >
        <DialogTitle id="rename-machine-title">Rename machine</DialogTitle>
        <DialogContent>
          <DialogContentText id="rename-machine-description">
            Your name is kept when Manabi reconnects. Leave blank to use its
            computer name.
          </DialogContentText>
          <TextField
            autoFocus
            fullWidth
            margin="normal"
            label="Machine name"
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
            slotProps={{ htmlInput: { maxLength: 120 } }}
          />
          {rename.isError && (
            <Alert severity="error">
              Could not rename this machine. {rename.error.message}
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button
            disabled={rename.isPending}
            onClick={() => setRenameOpen(false)}
          >
            Cancel
          </Button>
          <Button
            disabled={rename.isPending || !renameId}
            onClick={() =>
              renameId &&
              rename.mutate({ id: renameId, name: newName.trim() || null })
            }
          >
            Save
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog
        open={connectOpen}
        onClose={() => setConnectOpen(false)}
        maxWidth="sm"
        fullWidth
        aria-labelledby="remotes-dialog-title"
      >
        <DialogTitle id="remotes-dialog-title">Connect a machine</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Sign in with Kioku CLI, then run <code>kioku init</code> in any
            repository. It automatically installs and starts one Manabi service
            for your user on this computer.
          </DialogContentText>
          <DialogContentText sx={{ mt: 2 }}>
            Manabi starts at user login and reconnects automatically. Linux
            requires a working systemd user session. Memory collection is not
            included yet.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConnectOpen(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    </section>
  );
}
