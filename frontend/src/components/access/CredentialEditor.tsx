import { useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  FormControlLabel,
  TextField,
  Typography,
} from "@mui/material";
import { useAccessRequests } from "../../hooks/useAccessRequests";
import { accessError } from "../../lib/rootAccess";
import type { AccessCredential } from "../../lib/rootAccess";

export default function CredentialEditor({
  root,
  credential,
  onSaved,
  onBack,
}: {
  root: string;
  credential: AccessCredential;
  onSaved: () => void;
  onBack: () => void;
}) {
  const execute = useAccessRequests(root);
  const [values, setValues] = useState<Record<string, string>>({});
  const [region, setRegion] = useState(credential.region ?? "");
  const [expiry, setExpiry] = useState("");
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [blocked, setBlocked] = useState(!!credential.pending_operation_id);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const required = credential.fields.filter(
      (f) => !(credential.kind === "aws" && f === "session_token")
    );
    if (required.some((f) => !values[f])) {
      setError("Enter every required credential field.");
      return;
    }
    if (
      Object.values(values).some(
        (v) => v.includes("\0") || new TextEncoder().encode(v).length > 65536
      ) ||
      new TextEncoder().encode(JSON.stringify(values)).length > 262144
    ) {
      setError(
        "Use UTF-8 text without NUL, up to 64 KiB per field and 256 KiB total."
      );
      return;
    }
    if (
      credential.kind === "aws" &&
      Object.values(values).some((value) =>
        [...value].some(
          (char) => char.charCodeAt(0) <= 32 || char.charCodeAt(0) === 127
        )
      )
    ) {
      setError(
        "AWS credential fields cannot contain whitespace or control characters."
      );
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
    try {
      const metadata =
        region !== (credential.region ?? "") && !credential.legacy_binding_id
          ? await execute<AccessCredential>(
              `/credentials/${credential.id}`,
              "PATCH",
              { expected_revision: credential.revision, region }
            )
          : credential;
      await execute(`/credentials/${credential.id}/value`, "POST", {
        expected_revision: metadata.revision,
        idempotency_key: crypto.randomUUID(),
        values: Object.fromEntries(
          Object.entries(values).filter(([, v]) => v !== "")
        ),
        credential_expires_at: expiry ? new Date(expiry).toISOString() : null,
      });
      setValues({});
      onSaved();
      onBack();
    } catch (err) {
      setValues({});
      setBlocked(true);
      onSaved();
      setError(accessError(err));
    } finally {
      setBusy(false);
    }
  }
  async function reconcile() {
    setBusy(true);
    setValues({});
    setError("");
    try {
      await execute(`/credentials/${credential.id}/reconcile`, "POST", {});
      onSaved();
      onBack();
    } catch (err) {
      setError(accessError(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form
      className="access-form"
      autoComplete="off"
      onSubmit={(e) => void save(e)}
    >
      <Typography variant="h6">
        {credential.has_secret ? "Replace credential" : "Add credential"}
      </Typography>
      <Alert severity="info">
        Write-only storage. Saved values cannot be revealed here.
      </Alert>
      {error && <Alert severity="error">{error}</Alert>}
      {blocked && (
        <Alert severity="warning">
          Refresh and reconcile this credential before another write.
          <Button disabled={busy} onClick={() => void reconcile()}>
            Reconcile pending write
          </Button>
        </Alert>
      )}
      <FormControlLabel
        control={
          <Checkbox
            checked={visible}
            onChange={(e) => setVisible(e.target.checked)}
          />
        }
        label="Show values while editing"
      />
      {credential.fields.map((field) => (
        <TextField
          key={field}
          label={
            field === "session_token" && credential.kind === "aws"
              ? "Session token (optional)"
              : field.replaceAll("_", " ")
          }
          type={visible || field === "private_key" ? "text" : "password"}
          multiline={field === "private_key"}
          minRows={field === "private_key" ? 5 : undefined}
          value={values[field] ?? ""}
          onChange={(e) =>
            setValues((v) => ({ ...v, [field]: e.target.value }))
          }
          required={!(credential.kind === "aws" && field === "session_token")}
          disabled={busy || blocked}
          autoComplete="new-password"
          slotProps={{
            htmlInput: {
              maxLength: 65536,
              "data-secret": true,
              spellCheck: false,
            },
          }}
        />
      ))}
      {credential.kind === "aws" && (
        <Typography color="text.secondary" variant="body2">
          Omitting the session token removes it on replacement. Region is
          configured for this environment.
        </Typography>
      )}
      {credential.kind === "aws" && (
        <TextField
          label="Region (non-secret, optional)"
          value={region}
          disabled={busy || blocked || !!credential.legacy_binding_id}
          onChange={(e) => setRegion(e.target.value)}
          slotProps={{ htmlInput: { maxLength: 120 } }}
        />
      )}
      <TextField
        type="datetime-local"
        label="Expiration (optional)"
        value={expiry}
        onChange={(e) => setExpiry(e.target.value)}
        slotProps={{ inputLabel: { shrink: true } }}
        disabled={busy || blocked}
      />
      <div className="access-form-actions">
        <Button
          disabled={busy}
          onClick={() => {
            setValues({});
            onBack();
          }}
        >
          Back
        </Button>
        <Button type="submit" variant="contained" disabled={busy || blocked}>
          {busy ? "Saving…" : "Save credential"}
        </Button>
      </div>
    </form>
  );
}
