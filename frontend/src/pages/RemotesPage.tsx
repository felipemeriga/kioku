import { useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  TextField,
} from "@mui/material";
import AddIcon from "@mui/icons-material/Add";
import DesktopWindowsOutlinedIcon from "@mui/icons-material/DesktopWindowsOutlined";
import { brand } from "../theme";
import { getRemoteMachines, type RemoteMachine } from "../lib/api";
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
} as CSSProperties;
function date(value: string | null) {
  return value ? new Date(value).toLocaleString() : "Not connected yet";
}

export default function RemotesPage() {
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
      .includes(query.trim().toLowerCase())
  );
  const selected =
    matches.find((machine) => machine.id === selectedId) ?? matches[0];
  return (
    <main className="remotes-page" style={colors}>
      <header className="remotes-heading">
        <div>
          <h1>Remotes</h1>
          <p>Your machines. Connected through Manabi.</p>
        </div>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setConnectOpen(true)}
        >
          Connect machine
        </Button>
      </header>
      <div className="remotes-preview-note" role="note">
        <strong>Manabi</strong> Machine connection is available. Memory
        collection and agent session activity are coming later.
      </div>
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
        {machines.isError ? (
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
          </>
        )}
        <span>
          {machines.isError && all.length === 0
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
            {matches.map((machine) => (
              <button
                key={machine.id}
                className="remote-machine"
                aria-pressed={selected?.id === machine.id}
                onClick={() => setSelectedId(machine.id)}
              >
                <span className="remote-machine-name">
                  <DesktopWindowsOutlinedIcon fontSize="small" />
                  {machine.name}
                </span>
                <span className="remote-machine-meta">{machine.platform}</span>
                <span className="remote-machine-footer">
                  <span>
                    <i
                      className={`remote-dot ${
                        presence(machine) === "Online" ? "" : "offline"
                      }`}
                    />
                    {presence(machine)}
                  </span>
                  <span>Manabi {machine.version}</span>
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
                    {selected.platform} · Manabi {selected.version}
                  </p>
                </div>
              </div>
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
            <div className="remote-section-title">
              <h3>Connection</h3>
              <span>Authenticated outbound WebSocket</span>
            </div>
            <p>Registered {date(selected.created_at)}</p>
            <p>Last connected {date(selected.connected_at)}</p>
            {!selected.online && !machines.isError && (
              <div className="remotes-empty">
                <h3>This machine is offline</h3>
                <p>
                  Manabi reconnects automatically when the machine is awake, its
                  user service is running, and the backend is reachable.
                </p>
              </div>
            )}
            <div className="remote-section-title">
              <h3>Memory collection</h3>
              <span>Not enabled yet</span>
            </div>
            <p className="remote-footnote">
              This version maintains the connection only. It does not read
              memories, inspect agent sessions, or run remote commands.
            </p>
          </section>
        ) : (
          <div className="remote-detail remotes-empty">
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
              {machines.isError ? (
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
    </main>
  );
}
