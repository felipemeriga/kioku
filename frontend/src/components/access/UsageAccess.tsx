import { useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  Chip,
  FormControlLabel,
  MenuItem,
  TextField,
  Typography,
} from "@mui/material";
import type {
  AccessCatalog,
  AccessCredential,
  AccessUsage,
} from "../../lib/rootAccess";
import { accessError } from "../../lib/rootAccess";
import {
  usageCapabilities,
  usageFields,
  usagePreview,
} from "../../lib/accessUsage";
import { useAccessRequests } from "../../hooks/useAccessRequests";
export default function UsageAccess({
  root,
  catalog,
  usages,
  credentials,
  onSaved,
}: {
  root: string;
  catalog: AccessCatalog;
  usages: AccessUsage[];
  credentials: AccessCredential[];
  onSaved: () => void;
}) {
  const execute = useAccessRequests(root);
  const [device, setDevice] = useState("");
  const [usageId, setUsageId] = useState("");
  const [expiry, setExpiry] = useState("");
  const [ack, setAck] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const usage = usages.find((u) => u.id === usageId);
  const credential = credentials.find((c) => c.id === usage?.credential_id);
  const scopeKey = usage
    ? JSON.stringify([device, usage.id, usage.revision])
    : "";
  const approved = !!scopeKey && ack === scopeKey;
  const grants = (catalog.usage_grants ?? []).filter((g) =>
    usages.some((u) => u.id === g.usage_id)
  );
  async function grant(e: React.FormEvent) {
    e.preventDefault();
    if (!usage || !device || !approved) {
      setError("Choose a computer and recipe, and confirm its access scope.");
      return;
    }
    if (
      expiry &&
      (!Number.isFinite(Date.parse(expiry)) || Date.parse(expiry) <= Date.now())
    ) {
      setError("Choose a future expiration.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await execute("/usage-grants", "POST", {
        device_id: device,
        usage_id: usage.id,
        expected_usage_revision: usage.revision,
        allowed_fields: usageFields(usage.delivery),
        capabilities: usageCapabilities(usage.delivery),
        expires_at: expiry ? new Date(expiry).toISOString() : null,
      });
      setAck("");
      onSaved();
    } catch (err) {
      setError(accessError(err));
    } finally {
      setBusy(false);
    }
  }
  async function revoke(id: string) {
    setBusy(true);
    setError("");
    try {
      await execute(`/usage-grants/${id}/revoke`, "POST", {});
      onSaved();
    } catch (err) {
      setError(accessError(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="access-form">
      <Typography variant="body2" color="text.secondary">
        Only explicitly granted computers can use a recipe. The environment
        guide does not grant access.
      </Typography>
      {error && <Alert severity="error">{error}</Alert>}
      {grants
        .filter((g) => !g.revoked_at)
        .map((g) => {
          const recipe = usages.find((u) => u.id === g.usage_id);
          return (
            <div className="access-recipe-card" key={g.id}>
              <Typography fontWeight={600}>
                {catalog.devices.find((d) => d.id === g.device_id)?.label ??
                  "Unavailable computer"}
              </Typography>
              <Typography variant="body2">
                {recipe?.name} · revision {g.usage_revision}
              </Typography>
              <div className="access-pills">
                {g.allowed_fields.map((f) => (
                  <Chip size="small" key={f} label={f} />
                ))}
                {g.capabilities.map((c) => (
                  <Chip size="small" variant="outlined" key={c} label={c} />
                ))}
              </div>
              {recipe && recipe.revision !== g.usage_revision && (
                <Alert severity="warning">
                  Recipe changed. Revoke this grant and review the new revision.
                </Alert>
              )}
              <Button disabled={busy} onClick={() => void revoke(g.id)}>
                Revoke access
              </Button>
            </div>
          );
        })}
      {!!usages.length && (
        <form className="access-form" onSubmit={(e) => void grant(e)}>
          <Typography variant="subtitle2">Grant recipe access</Typography>
          <TextField
            select
            required
            label="Computer"
            value={device}
            onChange={(e) => setDevice(e.target.value)}
          >
            <MenuItem value="">Choose computer</MenuItem>
            {catalog.devices
              .filter(
                (d) => !d.revoked_at && Date.parse(d.expires_at) > Date.now()
              )
              .map((d) => (
                <MenuItem value={d.id} key={d.id}>
                  {d.label}
                </MenuItem>
              ))}
          </TextField>
          <TextField
            select
            required
            label="Usage recipe"
            value={usageId}
            onChange={(e) => {
              setUsageId(e.target.value);
              setAck("");
            }}
          >
            <MenuItem value="">Choose recipe</MenuItem>
            {usages.map((u) => (
              <MenuItem value={u.id} key={u.id}>
                {u.name} · {u.consumer}
              </MenuItem>
            ))}
          </TextField>
          {usage && (
            <Alert
              severity={usage.delivery.kind === "argv" ? "warning" : "info"}
            >
              Fields: {usageFields(usage.delivery).join(", ")}. Capabilities:{" "}
              {usageCapabilities(usage.delivery).join(", ")}. Revision{" "}
              {usage.revision}.
              <pre className="access-code">{usagePreview(usage.delivery)}</pre>
              {!credential?.has_secret &&
                " A credential value is not stored yet."}
            </Alert>
          )}
          <TextField
            label="Grant expiration (optional)"
            type="datetime-local"
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
            slotProps={{ inputLabel: { shrink: true } }}
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={approved}
                onChange={(e) => setAck(e.target.checked ? scopeKey : "")}
              />
            }
            label="Allow this computer to use these fields through this recipe revision."
          />
          <Button type="submit" variant="outlined" disabled={busy || !approved}>
            {busy ? "Saving…" : "Grant access"}
          </Button>
        </form>
      )}
      {!usages.length && (
        <Alert severity="info">
          Create a usage recipe before granting access.
        </Alert>
      )}
      <Typography variant="caption" color="text.secondary">
        Enroll or revoke computers in Computers & access. Existing legacy grants
        remain separate.
      </Typography>
    </div>
  );
}
