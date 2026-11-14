import { useAccessRequests } from "../../hooks/useAccessRequests";
import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  TextField,
  Typography,
} from "@mui/material";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { accessError, guideBytes } from "../../lib/rootAccess";
import type { AccessCatalog, AccessEnrollment } from "../../lib/rootAccess";

type GuideRevision = { revision: number; markdown: string; created_at: string };

type Props = { root: string; catalog: AccessCatalog; onSaved: () => void };
export function EnvironmentGuide({ root, catalog, onSaved }: Props) {
  const execute = useAccessRequests(root);
  const [text, setText] = useState(catalog.guide.markdown);
  const [baseRevision, setBaseRevision] = useState(catalog.guide.revision);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyBusy, setHistoryBusy] = useState(false);
  const [historyError, setHistoryError] = useState("");
  const [history, setHistory] = useState<GuideRevision[]>([]);
  const [selectedRevision, setSelectedRevision] = useState<number | null>(null);
  const revision = history.find((item) => item.revision === selectedRevision);
  async function loadHistory() {
    setHistoryOpen(true);
    setHistoryBusy(true);
    setHistoryError("");
    try {
      const rows = await execute<GuideRevision[]>("/guide/revisions", "GET");
      setHistory(rows);
      setSelectedRevision(rows[0]?.revision ?? null);
    } catch (e) {
      setHistoryError(accessError(e));
    } finally {
      setHistoryBusy(false);
    }
  }
  async function save() {
    if (guideBytes(text) > 65536) {
      setError("Keep the guide within 64 KiB.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const savedGuide = await execute<{ revision?: number }>("/guide", "PUT", {
        markdown: text,
        expected_revision: baseRevision,
      });
      setBaseRevision(savedGuide.revision ?? baseRevision + 1);
      onSaved();
      setSaved(true);
    } catch (e) {
      setError(accessError(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Box className="access-section-row" sx={{ mb: 3 }}>
        <Box>
          <Typography variant="h6">How your environments work</Typography>
          <Typography variant="body2" color="text.secondary">
            Give agents the context to choose the right resource.
          </Typography>
        </Box>
        <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
          <Button
            variant="outlined"
            disabled={historyBusy}
            onClick={() => void loadHistory()}
          >
            Revision history
          </Button>
          <Button
            variant="contained"
            onClick={() => void save()}
            disabled={busy}
          >
            {busy ? "Saving…" : "Save guide"}
          </Button>
        </Box>
      </Box>
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}
      {saved && (
        <Alert severity="success" sx={{ mb: 2 }}>
          Guide saved.
        </Alert>
      )}
      <Box className="access-guide-grid">
        <Box sx={{ minWidth: 0 }}>
          <TextField
            label="Markdown guide"
            fullWidth
            multiline
            minRows={18}
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setSaved(false);
            }}
            slotProps={{ htmlInput: { maxLength: 65536 } }}
            sx={{
              "& textarea": {
                fontFamily: "monospace",
                fontSize: 13,
                lineHeight: 1.8,
              },
            }}
          />
          <Typography variant="caption" color="text.secondary">
            Context only. Add credentials through the resource’s dedicated form.
          </Typography>
        </Box>
        <Box className="access-preview" aria-label="Guide preview">
          <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
            {text || "Your guide preview will appear here."}
          </ReactMarkdown>
        </Box>
      </Box>
      <Dialog
        open={historyOpen}
        onClose={() => setHistoryOpen(false)}
        fullWidth
        maxWidth="md"
        aria-labelledby="guide-history-title"
      >
        <DialogTitle id="guide-history-title">
          Guide revision history
        </DialogTitle>
        <DialogContent sx={{ minWidth: 0 }}>
          {historyBusy ? (
            <Box sx={{ display: "flex", gap: 2, alignItems: "center", py: 3 }}>
              <CircularProgress size={20} />
              <Typography>Loading revisions…</Typography>
            </Box>
          ) : historyError ? (
            <Alert
              severity="error"
              action={<Button onClick={() => void loadHistory()}>Retry</Button>}
            >
              {historyError}
            </Alert>
          ) : history.length ? (
            <Box
              sx={{
                display: "grid",
                gridTemplateColumns: {
                  xs: "minmax(0,1fr)",
                  sm: "180px minmax(0,1fr)",
                },
                gap: 2,
                minWidth: 0,
              }}
            >
              <Box
                component="nav"
                aria-label="Guide revisions"
                sx={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 1,
                  maxHeight: 440,
                  overflow: "auto",
                }}
              >
                {history.map((item) => (
                  <Button
                    key={item.revision}
                    aria-label={`View revision ${item.revision}`}
                    aria-pressed={selectedRevision === item.revision}
                    variant={
                      selectedRevision === item.revision ? "outlined" : "text"
                    }
                    onClick={() => setSelectedRevision(item.revision)}
                    sx={{ justifyContent: "flex-start", textAlign: "left" }}
                  >
                    <Box>
                      <Typography variant="body2">
                        Revision {item.revision}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {new Date(item.created_at).toLocaleDateString()}
                      </Typography>
                    </Box>
                  </Button>
                ))}
              </Box>
              <Box
                className="access-preview"
                aria-label="Revision preview"
                sx={{ maxHeight: 440, overflow: "auto" }}
              >
                <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
                  {revision?.markdown ?? "Choose a revision."}
                </ReactMarkdown>
              </Box>
            </Box>
          ) : (
            <Typography color="text.secondary" sx={{ py: 3 }}>
              No saved revisions yet.
            </Typography>
          )}
        </DialogContent>
        <DialogActions>
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ mr: "auto", px: 2 }}
          >
            Viewing history does not change your draft.
          </Typography>
          <Button onClick={() => setHistoryOpen(false)}>Close history</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
export function Environments({ root, catalog, onSaved }: Props) {
  const execute = useAccessRequests(root);
  const [editing, setEditing] = useState<string | null>(null);
  const [open, setOpen] = useState(false),
    [name, setName] = useState(""),
    [slug, setSlug] = useState(""),
    [sensitivity, setSensitivity] = useState("normal"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function save() {
    setError("");
    if (
      !name.trim() ||
      name.length > 120 ||
      !/^[a-z][a-z0-9-]{0,39}$/.test(slug) ||
      slug === "shared" ||
      catalog.environments.some((e) => e.slug === slug && e.id !== editing)
    ) {
      setError(
        "Enter a name and a unique lowercase identifier. “shared” is reserved.",
      );
      return;
    }
    setBusy(true);
    try {
      await execute(
        editing ? `/environments/${editing}` : "/environments",
        editing ? "PATCH" : "POST",
        {
          name: name.trim(),
          slug,
          sensitivity,
        },
      );
      setOpen(false);
      onSaved();
    } catch (e) {
      setError(accessError(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Box className="access-section-row" sx={{ mb: 3 }}>
        <Box>
          <Typography variant="h6">Environments</Typography>
          <Typography variant="body2" color="text.secondary">
            Names and boundaries used across this root.
          </Typography>
        </Box>
        <Button
          variant="outlined"
          onClick={() => {
            setOpen(true);
            setEditing(null);
            setSensitivity("normal");
            setError("");
            setName("");
            setSlug("");
          }}
        >
          Add environment
        </Button>
      </Box>
      {catalog.environments.map((e) => (
        <Box className="access-binding-row" key={e.id}>
          <Box>
            <Typography fontWeight={600}>{e.name}</Typography>
            <Typography variant="caption" color="text.secondary">
              {e.slug}
            </Typography>
          </Box>
          <Box
            sx={{
              display: "flex",
              gap: 1,
              alignItems: "center",
              flexWrap: "wrap",
            }}
          >
            <Chip
              size="small"
              label={e.sensitivity === "production" ? "Production" : "Standard"}
              color={e.sensitivity === "production" ? "warning" : "default"}
            />
            <Button
              size="small"
              aria-label={`Edit ${e.name}`}
              onClick={() => {
                setEditing(e.id);
                setName(e.name);
                setSlug(e.slug);
                setSensitivity(e.sensitivity);
                setError("");
                setOpen(true);
              }}
            >
              Edit
            </Button>
          </Box>
        </Box>
      ))}
      {!catalog.environments.length && (
        <Box className="access-empty">
          Add an environment before mapping environment-specific resources.
        </Box>
      )}
      <Alert severity="info" sx={{ mt: 3 }}>
        Shared tools such as Grafana don’t need a duplicate credential for every
        environment.
      </Alert>
      <Dialog
        open={open}
        onClose={() => !busy && setOpen(false)}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>
          {editing ? "Edit environment" : "Add an environment"}
        </DialogTitle>
        <DialogContent>
          <Box
            component="form"
            id="environment-form"
            className="access-form"
            sx={{ pt: 1 }}
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            {error && <Alert severity="error">{error}</Alert>}
            <TextField
              label="Name"
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              slotProps={{ htmlInput: { maxLength: 120 } }}
            />
            <TextField
              label="Identifier"
              required
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              helperText="Lowercase letters, numbers and hyphens."
              slotProps={{ htmlInput: { maxLength: 40 } }}
            />
            <TextField
              select
              label="Sensitivity"
              value={sensitivity}
              onChange={(e) => setSensitivity(e.target.value)}
            >
              <MenuItem value="normal">Standard</MenuItem>
              <MenuItem value="production">Production</MenuItem>
            </TextField>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button disabled={busy} onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            disabled={busy}
            type="submit"
            form="environment-form"
            variant="contained"
          >
            {editing ? "Save environment" : "Add environment"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
export function Computers({ root, catalog, onSaved }: Props) {
  const execute = useAccessRequests(root);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [revoke, setRevoke] = useState<string | null>(null),
    [grantDevice, setGrantDevice] = useState<string | null>(null),
    [bindingId, setBindingId] = useState(""),
    [expires, setExpires] = useState(""),
    [connect, setConnect] = useState(false);
  async function mutate(suffix: string, method: string, body?: unknown) {
    setBusy(true);
    setError("");
    try {
      await execute(suffix, method, body);
      onSaved();
      setRevoke(null);
      setGrantDevice(null);
    } catch (e) {
      setError(accessError(e));
    } finally {
      setBusy(false);
    }
  }
  const bindingLabel = (id: string) => {
    const b = catalog.bindings.find((v) => v.id === id);
    return b
      ? `${catalog.resources.find((r) => r.id === b.resource_id)?.name ?? "Resource"} / ${catalog.environments.find((e) => e.id === b.environment_id)?.name ?? "Shared"} / ${b.consumer}`
      : "Unavailable binding";
  };
  return (
    <>
      <Box className="access-section-row" sx={{ mb: 3 }}>
        <Box>
          <Typography variant="h6">Computers & access</Typography>
          <Typography variant="body2" color="text.secondary">
            Separate permissions for each computer.
          </Typography>
        </Box>
        <Button variant="outlined" onClick={() => setConnect(true)}>
          Connect a computer
        </Button>
      </Box>
      {error && <Alert severity="error">{error}</Alert>}
      {catalog.devices.map((d) => (
        <Box className="access-device" key={d.id}>
          <Box className="access-section-row">
            <Box sx={{ minWidth: 0 }}>
              <Typography fontWeight={600}>{d.label}</Typography>
              <Typography variant="caption" color="text.secondary">
                {d.revoked_at
                  ? "Access revoked"
                  : `Expires ${new Date(d.expires_at).toLocaleDateString()}`}
              </Typography>
            </Box>
            {!d.revoked_at && (
              <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
                <Button
                  size="small"
                  onClick={() => {
                    setGrantDevice(d.id);
                    setBindingId("");
                    setExpires("");
                    setError("");
                  }}
                >
                  Grant resource
                </Button>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => setRevoke(d.id)}
                >
                  Revoke computer
                </Button>
              </Box>
            )}
          </Box>
          <Box className="access-pills" sx={{ mt: 2 }}>
            {catalog.grants
              .filter((g) => g.device_id === d.id && !g.revoked_at)
              .map((g) => (
                <Chip
                  key={g.id}
                  size="small"
                  variant="outlined"
                  label={bindingLabel(g.binding_id)}
                  onDelete={
                    d.revoked_at || busy
                      ? undefined
                      : () => void mutate(`/grants/${g.id}`, "DELETE")
                  }
                  sx={{
                    maxWidth: "100%",
                    height: "auto",
                    "& .MuiChip-label": {
                      whiteSpace: "normal",
                      py: 0.5,
                      overflowWrap: "anywhere",
                    },
                  }}
                />
              ))}
          </Box>
        </Box>
      ))}
      {!catalog.devices.length && (
        <Box className="access-empty">
          Connect a computer to grant access to resources.
        </Box>
      )}
      <Typography variant="caption" color="text.secondary">
        Revoking blocks new requests. Rotate a credential to invalidate a value
        already delivered to a process.
      </Typography>
      <Dialog
        open={!!revoke}
        onClose={() => !busy && setRevoke(null)}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>Revoke computer access?</DialogTitle>
        <DialogContent>
          <Typography>
            New credential requests from this computer will be denied.
          </Typography>
          <Alert severity="warning" sx={{ mt: 2 }}>
            Running commands may already have credentials. Rotate them if
            necessary.
          </Alert>
          {error && (
            <Alert severity="error" sx={{ mt: 2 }}>
              {error}
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button disabled={busy} onClick={() => setRevoke(null)}>
            Keep access
          </Button>
          <Button
            disabled={busy}
            variant="contained"
            onClick={() => void mutate(`/devices/${revoke}/revoke`, "POST", {})}
          >
            Revoke access
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog
        open={!!grantDevice}
        onClose={() => !busy && setGrantDevice(null)}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>Grant resource access</DialogTitle>
        <DialogContent>
          <Box className="access-form" sx={{ pt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField
              select
              label="Resource mapping"
              value={bindingId}
              onChange={(e) => setBindingId(e.target.value)}
            >
              <MenuItem value="">Choose a mapping</MenuItem>
              {catalog.bindings
                .filter((b) => b.enabled)
                .map((b) => (
                  <MenuItem
                    key={b.id}
                    value={b.id}
                    sx={{ whiteSpace: "normal", overflowWrap: "anywhere" }}
                  >
                    {bindingLabel(b.id)}
                  </MenuItem>
                ))}
            </TextField>
            <TextField
              label="Grant expiration (optional)"
              type="datetime-local"
              value={expires}
              onChange={(e) => setExpires(e.target.value)}
              slotProps={{ inputLabel: { shrink: true } }}
            />
            <Alert severity="info">
              This permission applies only to the selected resource mapping.
            </Alert>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button disabled={busy} onClick={() => setGrantDevice(null)}>
            Cancel
          </Button>
          <Button
            disabled={busy}
            variant="contained"
            onClick={() => {
              if (!bindingId) {
                setError("Choose a resource mapping.");
                return;
              }
              if (
                expires &&
                (!Number.isFinite(Date.parse(expires)) ||
                  Date.parse(expires) <= Date.now())
              ) {
                setError("Choose a future expiration.");
                return;
              }
              void mutate("/grants", "POST", {
                device_id: grantDevice,
                binding_id: bindingId,
                expires_at: expires ? new Date(expires).toISOString() : null,
              });
            }}
          >
            Grant access
          </Button>
        </DialogActions>
      </Dialog>
      <Dialog
        open={connect}
        onClose={() => setConnect(false)}
        fullWidth
        maxWidth="sm"
      >
        <DialogTitle>Connect a computer</DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 2 }}>
            On that computer, run:
          </Typography>
          <code className="access-code">
            kioku access enroll --root {root} --file-credential-store
          </code>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
            Approve the browser request and select only the resource mappings it
            needs. The device token is stored in a separate owner-readable file
            on that computer. No local background service is required.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConnect(false)}>Done</Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
export function Activity({ catalog }: { catalog: AccessCatalog }) {
  return (
    <>
      <Typography variant="h6">Access activity</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Resource access only. Values and command output aren’t recorded here.
      </Typography>
      <Box className="access-activity">
        <table>
          <thead>
            <tr>
              <th>When</th>
              <th>Resource</th>
              <th>Computer</th>
              <th>Action</th>
              <th>Result</th>
            </tr>
          </thead>
          <tbody>
            {catalog.activity.map((e) => (
              <tr key={e.id}>
                <td>{new Date(e.created_at).toLocaleString()}</td>
                <td>
                  {catalog.resources.find((r) => r.id === e.resource_id)
                    ?.name ?? "Resource"}
                </td>
                <td>
                  {catalog.devices.find((d) => d.id === e.device_id)?.label ??
                    "Computer"}
                </td>
                <td>{e.action}</td>
                <td>{e.outcome}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!catalog.activity.length && (
          <Box className="access-empty">No access activity recorded yet.</Box>
        )}
      </Box>
    </>
  );
}
export function EnrollmentApproval({
  root,
  catalog,
  request,
  onDone,
}: {
  root: string;
  catalog: AccessCatalog;
  request: string;
  onDone: () => void;
}) {
  const execute = useAccessRequests(root);
  const [enrollment, setEnrollment] = useState<AccessEnrollment | null>(null),
    [chosen, setChosen] = useState<string[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  async function load() {
    setBusy(true);
    try {
      setEnrollment(
        await execute<AccessEnrollment>(
          `/enrollments/${encodeURIComponent(request)}`,
          "GET",
        ),
      );
    } catch (e) {
      setError(accessError(e));
    } finally {
      setBusy(false);
    }
  }
  async function decide(approve: boolean) {
    setBusy(true);
    try {
      await execute(
        `/enrollments/${encodeURIComponent(request)}/${approve ? "approve" : "deny"}`,
        "POST",
        approve ? { binding_ids: chosen } : {},
      );
      onDone();
    } catch (e) {
      setError(accessError(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog open fullWidth maxWidth="sm" onClose={onDone}>
      <DialogTitle>Connect this computer?</DialogTitle>
      <DialogContent>
        <Box className="access-form">
          {error && <Alert severity="error">{error}</Alert>}
          {!enrollment ? (
            <Button disabled={busy} onClick={() => void load()}>
              Review enrollment request
            </Button>
          ) : (
            <>
              <Typography fontWeight={600}>{enrollment.label}</Typography>
              <Typography variant="caption">
                Status: {enrollment.status} · expires{" "}
                {new Date(enrollment.expires_at).toLocaleString()}
              </Typography>
              <Typography variant="body2">
                Choose which mappings this computer can use.
              </Typography>
              {catalog.bindings
                .filter((b) => b.enabled)
                .map((b) => (
                  <FormControlLabel
                    key={b.id}
                    control={
                      <Checkbox
                        checked={chosen.includes(b.id)}
                        onChange={(e) =>
                          setChosen((p) =>
                            e.target.checked
                              ? [...p, b.id]
                              : p.filter((id) => id !== b.id),
                          )
                        }
                      />
                    }
                    label={`${catalog.resources.find((r) => r.id === b.resource_id)?.name ?? "Resource"} / ${catalog.environments.find((e) => e.id === b.environment_id)?.name ?? "Shared"} / ${b.consumer}`}
                  />
                ))}
            </>
          )}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button disabled={busy} onClick={() => void decide(false)}>
          Deny
        </Button>
        <Button
          variant="contained"
          disabled={busy || !enrollment || enrollment.status !== "pending"}
          onClick={() => void decide(true)}
        >
          Approve selected access
        </Button>
      </DialogActions>
    </Dialog>
  );
}
