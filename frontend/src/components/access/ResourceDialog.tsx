import { useAccessRequests } from "../../hooks/useAccessRequests";
import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Drawer,
  FormControlLabel,
  IconButton,
  MenuItem,
  TextField,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import type {
  AccessBinding,
  AccessCatalog,
  AccessResource,
} from "../../lib/rootAccess";
import {
  accessError,
  allowedClearVariable,
  mappingError,
  resourceError,
} from "../../lib/rootAccess";

type Props = {
  root: string;
  catalog: AccessCatalog;
  resource: AccessResource | null;
  onClose: () => void;
  onSaved: () => void;
};
export default function ResourceDialog({
  root,
  catalog,
  resource,
  onClose,
  onSaved,
}: Props) {
  const execute = useAccessRequests(root);
  const bindings = catalog.bindings.filter(
    (b) => b.resource_id === resource?.id,
  );
  const [bindingId, setBindingId] = useState(bindings[0]?.id ?? "");
  const binding = bindings.find((b) => b.id === bindingId);
  const [mode, setMode] = useState<
    "detail" | "resource" | "mapping" | "credential"
  >(resource ? "detail" : "resource");
  const [name, setName] = useState(resource?.name ?? "");
  const [description, setDescription] = useState(resource?.description ?? "");
  const [type, setType] = useState<AccessResource["type"]>(
    resource?.type ?? "database",
  );
  const [shared, setShared] = useState(resource?.shared ?? false);
  const [aliases, setAliases] = useState(resource?.aliases.join(", ") ?? "");
  const [account, setAccount] = useState(resource?.account ?? "");
  const [region, setRegion] = useState(resource?.region ?? "");
  const [environment, setEnvironment] = useState(binding?.environment_id ?? "");
  const [consumer, setConsumer] = useState(binding?.consumer ?? "");
  const [mapping, setMapping] = useState(
    binding
      ? Object.entries(binding.field_mapping)
          .map(([k, v]) => `${k}=${v}`)
          .join("\n")
      : "MONGO_URI=connection",
  );
  const [clearEnv, setClearEnv] = useState(binding?.clear_env.join(", ") ?? "");
  const [enabled, setEnabled] = useState(binding?.enabled ?? true);
  const [values, setValues] = useState<Record<string, string>>({});
  const [expiry, setExpiry] = useState("");
  const [multiline, setMultiline] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const reset = () => {
    setValues({});
    setError("");
    setExpiry("");
    setMultiline(false);
  };
  const close = () => {
    if (busy) return;
    reset();
    onClose();
  };
  const selectBinding = (b: AccessBinding) => {
    setBindingId(b.id);
    setEnvironment(b.environment_id ?? "");
    setConsumer(b.consumer);
    setMapping(
      Object.entries(b.field_mapping)
        .map(([k, v]) => `${k}=${v}`)
        .join("\n"),
    );
    setClearEnv(b.clear_env.join(", "));
    setEnabled(b.enabled);
    reset();
  };
  const save = async () => {
    setError("");
    if (binding?.pending_operation_id && mode !== "resource") {
      setError(
        "Reconcile the pending credential write before changing this mapping.",
      );
      return;
    }
    let suffix = "",
      method = "POST",
      body: unknown;
    if (mode === "resource") {
      const list = aliases
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const invalid = resourceError(name, list);
      if (invalid) {
        setError(invalid);
        return;
      }
      if (
        description.length > 4000 ||
        account.length > 120 ||
        region.length > 120
      ) {
        setError("Shorten the description, account or region.");
        return;
      }
      suffix = resource ? `/resources/${resource.id}` : "/resources";
      method = resource ? "PATCH" : "POST";
      body = {
        name: name.trim(),
        description,
        type,
        aliases: list,
        shared,
        account,
        region,
      };
    } else if (mode === "mapping") {
      const invalid = mappingError(mapping, resource?.type),
        clear = clearEnv
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean);
      if (invalid) {
        setError(invalid);
        return;
      }
      if (!consumer.trim() || consumer.length > 120) {
        setError("Enter an application name of 1–120 characters.");
        return;
      }
      if (!resource?.shared && !environment) {
        setError("Choose the environment for this mapping.");
        return;
      }
      if (clear.length > 32 || clear.some((v) => !allowedClearVariable(v))) {
        setError("Use up to 32 allowed variable names to clear.");
        return;
      }
      suffix = binding ? `/bindings/${binding.id}` : "/bindings";
      method = binding ? "PATCH" : "POST";
      body = {
        resource_id: resource!.id,
        environment_id: resource!.shared ? null : environment,
        consumer: consumer.trim(),
        field_mapping: Object.fromEntries(
          mapping
            .split("\n")
            .filter((l) => l.trim())
            .map((l) => l.split("=").map((s) => s.trim())),
        ),
        clear_env: clear,
        enabled,
        ...(binding ? { expected_revision: binding.revision } : {}),
      };
    } else if (mode === "credential" && binding) {
      const fields = [...new Set(Object.values(binding.field_mapping))];
      if (fields.some((f) => !values[f]?.length)) {
        setError("Enter a value for every required secret field.");
        return;
      }
      const size = new TextEncoder().encode(JSON.stringify(values)).length;
      if (
        size > 262144 ||
        Object.values(values).some(
          (v) => v.includes("\0") || new TextEncoder().encode(v).length > 65536,
        )
      ) {
        setError(
          "Each field must be UTF-8 text without NUL, up to 64 KiB (256 KiB total).",
        );
        return;
      }
      if (
        expiry &&
        (!Number.isFinite(Date.parse(expiry)) ||
          Date.parse(expiry) <= Date.now())
      ) {
        setError("Choose a future credential expiration.");
        return;
      }
      suffix = `/bindings/${binding.id}/credential`;
      body = {
        expected_revision: binding.revision,
        idempotency_key: crypto.randomUUID(),
        values,
        credential_expires_at: expiry ? new Date(expiry).toISOString() : null,
      };
    } else return;
    setBusy(true);
    try {
      await execute(suffix, method, body);
      setValues({});
      onSaved();
      onClose();
    } catch (err) {
      setValues({});
      onSaved();
      setError(accessError(err));
    } finally {
      setBusy(false);
    }
  };
  async function reconcile() {
    if (!binding) return;
    setBusy(true);
    setError("");
    setValues({});
    try {
      await execute(`/bindings/${binding.id}/credential/reconcile`, "POST", {});
      onSaved();
      setMode("detail");
    } catch (err) {
      setError(accessError(err));
    } finally {
      setBusy(false);
    }
  }
  const environmentName = (b: AccessBinding) =>
    b.environment_id
      ? (catalog.environments.find((e) => e.id === b.environment_id)?.name ??
        "Unavailable environment")
      : "Shared";
  return (
    <Drawer anchor="right" open onClose={close} className="access-drawer">
      <Box
        role="dialog"
        aria-modal="true"
        aria-labelledby="access-resource-title"
        sx={{
          display: "flex",
          flexDirection: "column",
          height: "100%",
          minWidth: 0,
        }}
      >
        <Box className="access-drawer-header">
          <Box className="access-section-row">
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="caption" color="text.secondary">
                Resources
              </Typography>
              <Typography
                id="access-resource-title"
                variant="h6"
                sx={{ overflowWrap: "anywhere" }}
              >
                {mode === "credential"
                  ? "Save credential"
                  : mode === "mapping"
                    ? "Application mapping"
                    : (resource?.name ?? "Add a resource")}
              </Typography>
            </Box>
            <IconButton
              onClick={close}
              disabled={busy}
              aria-label="Close resource"
            >
              <CloseIcon />
            </IconButton>
          </Box>
        </Box>
        <Box className="access-drawer-content">
          <form
            id="access-resource-form"
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
            autoComplete="off"
          >
            <Box className="access-form">
              {error && (
                <Alert severity="error" role="alert">
                  {error}
                </Alert>
              )}
              {binding?.pending_operation_id && (
                <Alert severity="warning">
                  <Typography variant="body2">
                    A credential write is pending. Reconcile it before replacing
                    the credential or editing its mapping.
                  </Typography>
                  <Button
                    disabled={busy}
                    onClick={() => void reconcile()}
                    size="small"
                  >
                    {busy ? "Recovering…" : "Reconcile pending write"}
                  </Button>
                </Alert>
              )}
              {mode === "resource" && (
                <>
                  <Typography color="text.secondary" variant="body2">
                    Describe the resource first. Credentials are added
                    separately.
                  </Typography>
                  <TextField
                    label="Resource name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    slotProps={{ htmlInput: { maxLength: 120 } }}
                    required
                  />
                  <TextField
                    select
                    label="Resource type"
                    value={type}
                    onChange={(e) =>
                      setType(e.target.value as AccessResource["type"])
                    }
                  >
                    {["database", "observability", "cloud", "other"].map(
                      (t) => (
                        <MenuItem key={t} value={t}>
                          {t[0].toUpperCase() + t.slice(1)}
                        </MenuItem>
                      ),
                    )}
                  </TextField>
                  <TextField
                    label="Description"
                    multiline
                    minRows={3}
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    slotProps={{ htmlInput: { maxLength: 4000 } }}
                  />
                  <TextField
                    label="Search aliases"
                    helperText="Comma-separated. Up to 20 aliases."
                    value={aliases}
                    onChange={(e) => setAliases(e.target.value)}
                    slotProps={{ htmlInput: { maxLength: 2420 } }}
                  />
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={shared}
                        onChange={(e) => setShared(e.target.checked)}
                      />
                    }
                    label="Shared across environments"
                  />
                  <Box className="access-split-fields">
                    <TextField
                      label="Account"
                      value={account}
                      onChange={(e) => setAccount(e.target.value)}
                      slotProps={{ htmlInput: { maxLength: 120 } }}
                    />
                    <TextField
                      label="Region"
                      value={region}
                      onChange={(e) => setRegion(e.target.value)}
                      slotProps={{ htmlInput: { maxLength: 120 } }}
                    />
                  </Box>
                </>
              )}
              {mode === "detail" && resource && (
                <>
                  <Typography color="text.secondary" variant="body2">
                    {resource.description}
                  </Typography>
                  <Box className="access-pills">
                    {bindings.map((b) => (
                      <Chip
                        key={b.id}
                        label={`${environmentName(b)} · ${b.consumer}`}
                        onClick={() => selectBinding(b)}
                        variant={b.id === bindingId ? "filled" : "outlined"}
                        color={b.id === bindingId ? "secondary" : "default"}
                        size="small"
                        sx={{
                          maxWidth: "100%",
                          height: "auto",
                          "& .MuiChip-label": {
                            whiteSpace: "normal",
                            overflowWrap: "anywhere",
                            py: 0.5,
                          },
                        }}
                      />
                    ))}
                  </Box>
                  <Button
                    variant="outlined"
                    size="small"
                    onClick={() => {
                      setBindingId("");
                      setEnvironment("");
                      setConsumer("");
                      setMapping("CONNECTION_URI=connection");
                      setClearEnv("");
                      setMode("mapping");
                    }}
                  >
                    Add application mapping
                  </Button>
                  {binding ? (
                    <>
                      <Typography variant="subtitle2">Credential</Typography>
                      <Box className="access-device" sx={{ m: 0 }}>
                        <Box className="access-section-row">
                          <Box>
                            <Typography fontWeight={600}>
                              {binding.has_secret
                                ? "Stored in central vault"
                                : "No credential stored"}
                            </Typography>
                            <Typography
                              variant="caption"
                              color="text.secondary"
                            >
                              {binding.has_secret
                                ? "Value hidden · replacement only"
                                : "Add a credential for this binding."}
                            </Typography>
                          </Box>
                          <Button
                            size="small"
                            variant="outlined"
                            disabled={!!binding.pending_operation_id}
                            onClick={() => {
                              reset();
                              setMode("credential");
                            }}
                          >
                            {binding.has_secret ? "Replace" : "Add credential"}
                          </Button>
                        </Box>
                      </Box>
                      <Typography variant="subtitle2">
                        Application mapping
                      </Typography>
                      <Box>
                        {Object.entries(binding.field_mapping).map(
                          ([variable, field]) => (
                            <Box className="access-binding-row" key={variable}>
                              <span>
                                {binding.consumer} / {field}
                              </span>
                              <code className="access-code">{variable}</code>
                            </Box>
                          ),
                        )}
                      </Box>
                      <Button
                        size="small"
                        variant="outlined"
                        disabled={!!binding.pending_operation_id}
                        onClick={() => setMode("mapping")}
                      >
                        Edit mapping
                      </Button>
                      {binding.environment_id &&
                        catalog.environments.find(
                          (e) => e.id === binding.environment_id,
                        )?.sensitivity === "production" && (
                          <Alert severity="warning">
                            Production requires an explicit grant for each
                            computer.
                          </Alert>
                        )}
                      <Typography variant="subtitle2">
                        Computer access
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        {
                          catalog.grants.filter(
                            (g) => g.binding_id === binding.id && !g.revoked_at,
                          ).length
                        }{" "}
                        active grants. Manage permissions in Computers & access.
                      </Typography>
                    </>
                  ) : (
                    <Alert severity="info">
                      Add an application mapping and environment before storing
                      a credential.
                    </Alert>
                  )}
                  <Typography variant="subtitle2">
                    How agents find it
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {resource.aliases.join(", ") || "No aliases yet."}
                  </Typography>
                  <Button size="small" onClick={() => setMode("resource")}>
                    Edit resource details
                  </Button>
                </>
              )}
              {mode === "mapping" && (
                <>
                  <Typography variant="body2" color="text.secondary">
                    {resource?.name}
                  </Typography>
                  {!resource?.shared ? (
                    <TextField
                      select
                      required
                      label="Environment"
                      value={environment}
                      onChange={(e) => setEnvironment(e.target.value)}
                    >
                      <MenuItem value="">Choose environment</MenuItem>
                      {catalog.environments.map((e) => (
                        <MenuItem key={e.id} value={e.id}>
                          {e.name}
                        </MenuItem>
                      ))}
                    </TextField>
                  ) : (
                    <Alert severity="info">
                      This resource is shared across environments.
                    </Alert>
                  )}
                  <TextField
                    label="Application or crate"
                    value={consumer}
                    onChange={(e) => setConsumer(e.target.value)}
                    slotProps={{ htmlInput: { maxLength: 120 } }}
                    required
                  />
                  <TextField
                    label="Variable mappings"
                    multiline
                    minRows={4}
                    helperText="One per line: MONGO_URI=connection. Values here are secret field names, never credentials."
                    value={mapping}
                    onChange={(e) => setMapping(e.target.value)}
                    slotProps={{ htmlInput: { maxLength: 8192 } }}
                  />
                  <TextField
                    label="Clear inherited variables"
                    value={clearEnv}
                    onChange={(e) => setClearEnv(e.target.value)}
                    helperText="Comma-separated alternative credential selectors to remove."
                    slotProps={{ htmlInput: { maxLength: 4096 } }}
                  />
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={enabled}
                        onChange={(e) => setEnabled(e.target.checked)}
                      />
                    }
                    label="Mapping enabled"
                  />
                  <Alert severity="info">
                    Mapping does not grant a computer permission to use this
                    resource.
                  </Alert>
                </>
              )}
              {mode === "credential" && binding && (
                <>
                  <Typography color="text.secondary" variant="body2">
                    {resource?.name} / {environmentName(binding)}
                  </Typography>
                  <Alert severity="info">
                    Values are sent only to the vault and cannot be revealed
                    here. Do not paste credentials into the environment guide.
                  </Alert>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={multiline}
                        onChange={(e) => {
                          setValues({});
                          setMultiline(e.target.checked);
                        }}
                      />
                    }
                    label="Enter a multiline value (visible while editing)"
                  />
                  {[...new Set(Object.values(binding.field_mapping))].map(
                    (field) => (
                      <TextField
                        key={field}
                        label={`Secret field: ${field}`}
                        type={multiline ? "text" : "password"}
                        multiline={multiline}
                        minRows={multiline ? 4 : undefined}
                        autoComplete="new-password"
                        value={values[field] ?? ""}
                        onChange={(e) =>
                          setValues((v) => ({ ...v, [field]: e.target.value }))
                        }
                        slotProps={{
                          htmlInput: { maxLength: 65536, "data-secret": true },
                        }}
                        required
                      />
                    ),
                  )}
                  <TextField
                    label="Credential expiration (optional)"
                    type="datetime-local"
                    value={expiry}
                    onChange={(e) => setExpiry(e.target.value)}
                    slotProps={{ inputLabel: { shrink: true } }}
                  />
                  <Typography variant="caption" color="text.secondary">
                    Secret fields are cleared when you leave this form or after
                    a failed request.
                  </Typography>
                </>
              )}
            </Box>
          </form>
        </Box>
        <Box className="access-drawer-footer">
          {mode !== "detail" && resource ? (
            <Button
              disabled={busy}
              onClick={() => {
                reset();
                setMode("detail");
              }}
            >
              Back
            </Button>
          ) : (
            <Button disabled={busy} onClick={close}>
              {mode === "detail" ? "Done" : "Cancel"}
            </Button>
          )}
          {mode !== "detail" && (
            <Button
              type="submit"
              form="access-resource-form"
              variant="contained"
              disabled={busy || !!binding?.pending_operation_id}
            >
              {busy
                ? "Saving…"
                : mode === "credential"
                  ? "Save credential"
                  : mode === "mapping"
                    ? "Save mapping"
                    : "Save resource"}
            </Button>
          )}
        </Box>
      </Box>
    </Drawer>
  );
}
