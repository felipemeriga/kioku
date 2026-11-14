import { useState } from "react";
import {
  Alert,
  Button,
  Checkbox,
  FormControlLabel,
  MenuItem,
  TextField,
  Typography,
} from "@mui/material";
import type {
  AccessCredential,
  AccessUsage,
  UsageDelivery,
} from "../../lib/rootAccess";
import { accessError } from "../../lib/rootAccess";
import { usageError } from "../../lib/accessUsage";
import { useAccessRequests } from "../../hooks/useAccessRequests";
type Row = { target: string; field: string };
export default function UsageEditor({
  root,
  credential,
  usage,
  onSaved,
  onBack,
}: {
  root: string;
  credential: AccessCredential;
  usage?: AccessUsage;
  onSaved: () => void;
  onBack: () => void;
}) {
  const execute = useAccessRequests(root);
  const initial = usage?.delivery;
  const [name, setName] = useState(usage?.name ?? "");
  const [consumer, setConsumer] = useState(usage?.consumer ?? "");
  const [kind, setKind] = useState<UsageDelivery["kind"]>(
    initial?.kind ?? (credential.kind === "ssh" ? "ssh" : "env")
  );
  const [rows, setRows] = useState<Row[]>(
    initial?.kind === "env"
      ? Object.entries(initial.field_mapping).map(([target, field]) => ({
          target,
          field,
        }))
      : initial?.kind === "file"
      ? initial.patches.map((p) => ({
          target: p.path.join("."),
          field: p.field,
        }))
      : credential.kind === "aws"
      ? credential.fields.map((field) => ({
          target: `AWS_${field.toUpperCase()}`,
          field,
        }))
      : [{ target: "", field: credential.fields[0] ?? "" }]
  );
  const [clear, setClear] = useState(
    initial?.kind === "env" ? initial.clear_env.join(", ") : ""
  );
  const [format, setFormat] = useState<"json" | "yaml" | "toml">(
    initial?.kind === "file" ? initial.format : "json"
  );
  const [template, setTemplate] = useState(
    initial?.kind === "file" ? initial.source_template : ""
  );
  const [destination, setDestination] = useState<"env" | "arg">(
    initial?.kind === "file" ? initial.destination.kind : "arg"
  );
  const [destinationName, setDestinationName] = useState(
    initial?.kind === "file" ? initial.destination.name : "--config"
  );
  const [args, setArgs] = useState(
    initial?.kind === "argv"
      ? initial.arguments
          .map((a) =>
            a.kind === "literal" ? a.value : `credential.${a.field}`
          )
          .join("\n")
      : ""
  );
  const [ack, setAck] = useState(
    initial?.kind === "argv" ? initial.allow_raw_secret_argv : false
  );
  const [host, setHost] = useState(initial?.kind === "ssh" ? initial.host : "");
  const [user, setUser] = useState(initial?.kind === "ssh" ? initial.user : "");
  const [port, setPort] = useState(
    initial?.kind === "ssh" ? String(initial.port) : "22"
  );
  const [hostKey, setHostKey] = useState(
    initial?.kind === "ssh" ? initial.host_key : ""
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function save(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (
      !name.trim() ||
      name.length > 120 ||
      !consumer.trim() ||
      consumer.length > 120
    ) {
      setError("Enter a name and application of 1–120 characters.");
      return;
    }
    let delivery: UsageDelivery;
    if (kind === "env") {
      if (new Set(rows.map((r) => r.target.trim())).size !== rows.length) {
        setError("Each destination variable must be unique.");
        return;
      }
      delivery = {
        kind,
        field_mapping: Object.fromEntries(
          rows.map((r) => [r.target.trim(), r.field])
        ),
        clear_env: clear
          .split(",")
          .map((v) => v.trim())
          .filter(Boolean),
      };
    } else if (kind === "file")
      delivery = {
        kind,
        format,
        source_template: template,
        patches: rows.map((r) => ({
          path: r.target.split("."),
          field: r.field,
        })),
        destination: { kind: destination, name: destinationName },
      };
    else if (kind === "argv")
      delivery = {
        kind,
        allow_raw_secret_argv: ack,
        arguments: args
          .split("\n")
          .filter(Boolean)
          .map((a) =>
            a.startsWith("credential.")
              ? { kind: "field", field: a.slice(11) }
              : { kind: "literal", value: a }
          ),
      };
    else
      delivery = {
        kind,
        host,
        user,
        port: Number(port),
        host_key: hostKey,
        private_key_field: "private_key",
        passphrase_field: credential.fields.includes("passphrase")
          ? "passphrase"
          : null,
      };
    const invalid = usageError(delivery, credential);
    if (invalid) {
      setError(invalid);
      return;
    }
    setBusy(true);
    try {
      await execute(
        usage ? `/usages/${usage.id}` : "/usages",
        usage ? "PATCH" : "POST",
        {
          credential_id: credential.id,
          name: name.trim(),
          consumer: consumer.trim(),
          delivery,
          enabled: true,
          ...(usage ? { expected_revision: usage.revision } : {}),
        }
      );
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
      onSubmit={(e) => void save(e)}
      autoComplete="off"
    >
      <Typography variant="h6">
        {usage ? "Edit usage recipe" : "Add usage recipe"}
      </Typography>
      {error && <Alert severity="error">{error}</Alert>}
      <TextField
        label="Recipe name"
        required
        value={name}
        onChange={(e) => setName(e.target.value)}
        slotProps={{ htmlInput: { maxLength: 120 } }}
      />
      <TextField
        label="Application or repository"
        required
        value={consumer}
        onChange={(e) => setConsumer(e.target.value)}
        slotProps={{ htmlInput: { maxLength: 120 } }}
      />
      <TextField
        select
        label="Delivery method"
        value={kind}
        onChange={(e) => {
          const next = e.target.value as UsageDelivery["kind"];
          setKind(next);
          if (credential.kind === "aws") {
            setRows(
              credential.fields.map((field) => ({
                field,
                target:
                  next === "file"
                    ? `default.aws_${field}`
                    : `AWS_${field.toUpperCase()}`,
              }))
            );
            if (next === "file") {
              setFormat("toml");
              setTemplate("[default]\n");
              setDestination("env");
              setDestinationName("AWS_SHARED_CREDENTIALS_FILE");
            }
          }
        }}
      >
        {[
          ["env", "Environment variables"],
          ["file", "Temporary configuration file"],
          ...(credential.kind !== "aws"
            ? [
                ["argv", "Command arguments"],
                ["ssh", "SSH identity"],
              ]
            : []),
        ].map(([v, label]) => (
          <MenuItem value={v} key={v}>
            {label}
          </MenuItem>
        ))}
      </TextField>
      {(kind === "env" || kind === "file") && (
        <>
          <Typography variant="body2" color="text.secondary">
            Reference credential field names only. All mappings apply together.
          </Typography>
          {rows.map((r, i) => (
            <div className="access-mapping-row" key={i}>
              <TextField
                size="small"
                label={
                  kind === "env" ? "Variable name" : "Key path (dot separated)"
                }
                value={r.target}
                onChange={(e) =>
                  setRows((old) =>
                    old.map((v, j) =>
                      j === i ? { ...v, target: e.target.value } : v
                    )
                  )
                }
              />
              <TextField
                size="small"
                select
                label="Credential field"
                value={r.field}
                onChange={(e) =>
                  setRows((old) =>
                    old.map((v, j) =>
                      j === i ? { ...v, field: e.target.value } : v
                    )
                  )
                }
              >
                {credential.fields.map((f) => (
                  <MenuItem key={f} value={f}>
                    {f}
                  </MenuItem>
                ))}
              </TextField>
              <Button
                aria-label={`Remove mapping ${i + 1}`}
                disabled={rows.length === 1}
                onClick={() => setRows((old) => old.filter((_, j) => j !== i))}
              >
                Remove
              </Button>
            </div>
          ))}
          <Button
            disabled={rows.length >= 32}
            onClick={() =>
              setRows((old) => [
                ...old,
                { target: "", field: credential.fields[0] },
              ])
            }
          >
            Add field mapping
          </Button>
        </>
      )}
      {credential.kind === "aws" && (
        <Alert severity="info">
          AWS key ID, secret key and optional session token form one bundle.
          Region comes from the selected environment’s credential metadata.
          Temporary profile delivery uses a protected AWS credentials file with
          a default profile.
        </Alert>
      )}
      {kind === "env" && (
        <TextField
          label="Clear inherited variables (optional)"
          value={clear}
          onChange={(e) => setClear(e.target.value)}
          helperText="Comma-separated names. AWS selectors are cleared automatically."
        />
      )}
      {kind === "file" && (
        <>
          {credential.kind !== "aws" && (
            <TextField
              select
              label="File format"
              value={format}
              onChange={(e) => setFormat(e.target.value as typeof format)}
            >
              {["json", "yaml", "toml"].map((f) => (
                <MenuItem value={f} key={f}>
                  {f.toUpperCase()}
                </MenuItem>
              ))}
            </TextField>
          )}
          <TextField
            label="Nonsecret source template"
            multiline
            minRows={5}
            value={template}
            onChange={(e) => setTemplate(e.target.value)}
            slotProps={{ htmlInput: { maxLength: 65536, spellCheck: false } }}
            helperText="A protected temporary copy receives the credential fields. Never paste secrets into this template."
          />
          <div className="access-split-fields">
            <TextField
              select
              disabled={credential.kind === "aws"}
              label="Pass file path through"
              value={destination}
              onChange={(e) =>
                setDestination(e.target.value as typeof destination)
              }
            >
              <MenuItem value="arg">CLI argument</MenuItem>
              <MenuItem value="env">Environment variable</MenuItem>
            </TextField>
            <TextField
              disabled={credential.kind === "aws"}
              label="Destination name"
              value={destinationName}
              onChange={(e) => setDestinationName(e.target.value)}
            />
          </div>
        </>
      )}
      {kind === "argv" && (
        <>
          <TextField
            label="Arguments (one per line)"
            value={args}
            onChange={(e) => setArgs(e.target.value)}
            multiline
            minRows={4}
            helperText="Use credential.field_name for a secret field; other lines are nonsecret literal arguments. No shell expansion."
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={ack}
                onChange={(e) => setAck(e.target.checked)}
              />
            }
            label="I understand raw secrets in arguments may appear in process lists."
          />
        </>
      )}
      {kind === "ssh" && (
        <>
          <div className="access-split-fields">
            <TextField
              required
              label="Host"
              value={host}
              onChange={(e) => setHost(e.target.value)}
            />
            <TextField
              required
              label="User"
              value={user}
              onChange={(e) => setUser(e.target.value)}
            />
          </div>
          <TextField
            required
            label="Port"
            type="number"
            value={port}
            onChange={(e) => setPort(e.target.value)}
          />
          <TextField
            required
            label="Trusted host public key"
            multiline
            minRows={2}
            value={hostKey}
            onChange={(e) => setHostKey(e.target.value)}
            helperText="ssh-ed25519 BASE64. Confirm through a trusted source; unknown hosts are never accepted automatically."
          />
        </>
      )}
      <Alert severity="info">
        Recipes describe usage. A computer still needs an explicit grant.
        Editing a recipe requires a new grant.
      </Alert>
      <div className="access-form-actions">
        <Button disabled={busy} onClick={onBack}>
          Back
        </Button>
        <Button type="submit" variant="contained" disabled={busy}>
          {busy ? "Saving…" : "Save recipe"}
        </Button>
      </div>
    </form>
  );
}
