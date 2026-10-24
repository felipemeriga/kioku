import { useState, type CSSProperties } from "react";
import {
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
import FolderOutlinedIcon from "@mui/icons-material/FolderOutlined";
import { brand } from "../theme";
import { remotesPreview } from "./remotesPreview";
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

type PreviewDialog = "connect" | "manage" | "issue" | null;

export default function RemotesPage() {
  const [selectedId, setSelectedId] = useState(remotesPreview[0].id);
  const [query, setQuery] = useState("");
  const [dialog, setDialog] = useState<PreviewDialog>(null);
  const matches = remotesPreview.filter((machine) =>
    `${machine.name} ${machine.platform} ${machine.host}`
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
          <p>Your machines. Your agents. Learning stays connected.</p>
        </div>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setDialog("connect")}
        >
          Connect machine
        </Button>
      </header>
      <div className="remotes-preview-note" role="note">
        <strong>Preview</strong> Sample machines and activity. Live connections
        and memory sync are not available yet.
      </div>
      <div className="remotes-fleet">
        <span>
          <i className="remote-dot" />2 machines online
        </span>
        <span>
          <i className="remote-dot warning" />1 needs attention
        </span>
        <span>3 sample machines</span>
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
                <span className="remote-machine-meta">
                  {machine.platform} · {machine.host}
                </span>
                <span className="remote-machine-footer">
                  <span>
                    <i
                      className={`remote-dot ${
                        machine.online ? "" : "offline"
                      }`}
                    />
                    {machine.online ? "Online" : "Offline"}
                  </span>
                  <span
                    className={machine.issue ? "remote-warning" : undefined}
                  >
                    {machine.issue
                      ? "1 sync issue"
                      : machine.online
                      ? "Up to date"
                      : `Last seen ${machine.heartbeat}`}
                  </span>
                </span>
              </button>
            ))}
          </div>
          {matches.length === 0 && (
            <p className="remotes-empty">
              No machines match “{query}”. Try a different name or operating
              system.
            </p>
          )}
          <p className="remotes-machine-help">
            Only repositories initialized with <code>kioku init</code> will
            contribute memories from a connected machine.
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
                    {selected.platform} · Connected {selected.connected}
                  </p>
                </div>
              </div>
              <Button
                size="small"
                variant="outlined"
                onClick={() => setDialog("manage")}
              >
                Manage machine
              </Button>
            </header>
            <div className="remote-statusbar">
              <span>
                <i
                  className={`remote-dot ${selected.online ? "" : "offline"}`}
                />
                <strong>{selected.online ? "Online" : "Offline"}</strong>
              </span>
              <span>
                {selected.online ? "Last heartbeat" : "Last seen"}{" "}
                {selected.heartbeat}
              </span>
              <span>Last successful sync {selected.lastSync}</span>
            </div>
            {!selected.online ? (
              <div className="remotes-empty">
                <h3>This machine is offline</h3>
                <p>
                  Its local service last connected {selected.heartbeat}. Memory
                  sync will resume when it reconnects.
                </p>
                <p>
                  Previously imported knowledge remains available to your
                  agents.
                </p>
              </div>
            ) : (
              <>
                {selected.issue && (
                  <div className="remote-issue">
                    <div>
                      <strong>{selected.issue}</strong>
                      <p>
                        No native memories found for c360-lead. Claude
                        collection is working.
                      </p>
                    </div>
                    <Button
                      size="small"
                      color="warning"
                      variant="outlined"
                      onClick={() => setDialog("issue")}
                    >
                      View issue
                    </Button>
                  </div>
                )}
                <div className="remote-section-title">
                  <h3>
                    Repositories <span>{selected.repos.length}</span>
                  </h3>
                  <span>Memory sync on this machine</span>
                </div>
                <div
                  className="remote-repos"
                  aria-label="Initialized repositories"
                >
                  {selected.repos.map((repo) => (
                    <div className="remote-repo" key={repo.path}>
                      <div className="remote-repo-identity">
                        <strong>
                          <FolderOutlinedIcon fontSize="small" />
                          {repo.name}
                        </strong>
                        <code>{repo.path}</code>
                      </div>
                      <div className="remote-repo-count">
                        <strong>
                          {repo.imported} imported
                          {repo.pending > 0 && ` · ${repo.pending} pending`}
                        </strong>
                        <span>Last sync {repo.lastSync}</span>
                      </div>
                      <span
                        className={`remote-repo-status ${
                          repo.status === "Needs attention"
                            ? "remote-warning"
                            : repo.status === "Syncing"
                            ? "remote-syncing"
                            : ""
                        }`}
                      >
                        {repo.status}
                      </span>
                    </div>
                  ))}
                </div>
                <p className="remote-footnote">
                  Imported counts are memories received, not accepted findings.
                </p>
                <div className="remote-section-title">
                  <h3>Agents & sessions</h3>
                  <span>Latest observed activity</span>
                </div>
                <div className="remote-agents">
                  {selected.agents.map((agent) => (
                    <div className="remote-agent" key={agent.name}>
                      <div className="remote-agent-heading">
                        <strong>
                          <span
                            className="remote-provider-mark"
                            aria-hidden="true"
                          >
                            {agent.name === "Codex" ? "›_" : "✳"}
                          </span>
                          {agent.name}
                        </strong>
                        <span
                          className={`remote-pill ${
                            agent.status === "Recently active" ? "active" : ""
                          }`}
                        >
                          {agent.status}
                        </span>
                      </div>
                      {agent.project && (
                        <p className="remote-agent-project">{agent.project}</p>
                      )}
                      <p>
                        {agent.activity}
                        {agent.session && (
                          <>
                            {" "}
                            · Session <code>{agent.session}</code>
                          </>
                        )}
                        <br />
                        {agent.collection}
                      </p>
                    </div>
                  ))}
                </div>
                <p className="remote-footnote">
                  Activity reflects the latest local signal. A running agent may
                  be idle.
                </p>
                <div className="remote-section-title">
                  <h3>Latest sync</h3>
                  <span>Sample activity</span>
                </div>
                {selected.activity.map((entry) => (
                  <div className="remote-activity" key={entry.text}>
                    <span aria-hidden="true">↥</span>
                    <span>
                      <strong>{entry.text}</strong> · {entry.detail}
                    </span>
                    <time>{entry.time}</time>
                  </div>
                ))}
              </>
            )}
          </section>
        ) : (
          <div className="remote-detail remotes-empty">
            Clear the search to browse sample machines.
          </div>
        )}
      </div>
      <footer className="remotes-footer">
        Local services will sync agent memories. Cloud repository indexing
        continues independently.
      </footer>
      <Dialog
        open={dialog !== null}
        onClose={() => setDialog(null)}
        maxWidth="sm"
        fullWidth
        aria-labelledby="remotes-dialog-title"
      >
        <DialogTitle id="remotes-dialog-title">
          {dialog === "connect"
            ? "Connect a machine"
            : dialog === "issue"
            ? "Codex memory collection"
            : `Manage ${selected?.name ?? "machine"}`}
        </DialogTitle>
        <DialogContent>
          {dialog === "connect" ? (
            <>
              <DialogContentText>
                Machine connections are coming next. This preview does not
                register your computer or start a local service.
              </DialogContentText>
              <DialogContentText sx={{ mt: 2 }}>
                The planned setup will connect repositories through Kioku CLI.
                Installation and connection instructions will appear here when
                available.
              </DialogContentText>
            </>
          ) : dialog === "issue" ? (
            <>
              <DialogContentText>
                This is an example collection issue for c360-lead on meriga-dev.
                The memory store contains no extracted Codex memories, while
                Claude collection is up to date.
              </DialogContentText>
              <DialogContentText sx={{ mt: 2 }}>
                With live connections, this panel will show the collector’s
                latest diagnostic and suggested next step.
              </DialogContentText>
            </>
          ) : (
            <DialogContentText>
              Rename, pause sync, and disconnect controls will be available
              after machine connections are added. This preview cannot change
              any machine settings.
            </DialogContentText>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDialog(null)}>Close</Button>
        </DialogActions>
      </Dialog>
    </main>
  );
}
