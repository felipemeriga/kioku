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
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import type {
  AccessCatalog,
  AccessCredential,
  AccessResource,
  AccessUsage,
  CredentialKind,
} from "../../lib/rootAccess";
import { accessError, resourceError } from "../../lib/rootAccess";
import { useAccessRequests } from "../../hooks/useAccessRequests";
import CredentialEditor from "./CredentialEditor";
import UsageEditor from "./UsageEditor";
import UsageAccess from "./UsageAccess";
import LegacyResourceDialog from "./LegacyResourceDialog";
const kindLabels: Record<CredentialKind, string> = {
  uri: "Connection URI",
  api_key: "API key",
  ssh: "SSH key",
  fields: "Custom credential bundle",
  aws: "AWS credentials",
};
const defaults: Record<CredentialKind, string[]> = {
  uri: ["connection"],
  api_key: ["api_key"],
  ssh: ["private_key"],
  fields: ["connection"],
  aws: ["access_key_id", "secret_access_key", "session_token"],
};
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
  const current =
    catalog.resources.find((r) => r.id === resource?.id) ?? resource;
  const [mode, setMode] = useState<
    "detail" | "resource" | "credential" | "usage" | "legacy"
  >(resource ? "detail" : "resource");
  const [tab, setTab] = useState(0);
  const [selected, setSelected] = useState<AccessCredential>();
  const [usage, setUsage] = useState<AccessUsage>();
  const [name, setName] = useState(resource?.name ?? "");
  const [description, setDescription] = useState(resource?.description ?? "");
  const [type, setType] = useState<AccessResource["type"]>(
    resource?.type ?? "database"
  );
  const [aliases, setAliases] = useState(resource?.aliases.join(", ") ?? "");
  const [shared, setShared] = useState(resource?.shared ?? false);
  const [envs, setEnvs] = useState<string[]>(resource?.environment_ids ?? []);
  const [kind, setKind] = useState<CredentialKind>(
    resource?.credential_kind ?? "uri"
  );
  const [fields, setFields] = useState(
    (resource?.credential_fields ?? ["connection"]).join(", ")
  );
  const [account, setAccount] = useState(resource?.account ?? "");
  const [region, setRegion] = useState(resource?.region ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const credentials = (catalog.credentials ?? []).filter(
    (c) => c.resource_id === resource?.id
  );
  const usages = (catalog.usages ?? []).filter((u) =>
    credentials.some((c) => c.id === u.credential_id)
  );
  const legacy = catalog.bindings.filter((b) => b.resource_id === resource?.id);
  const environmentName = (id: string | null) =>
    id
      ? catalog.environments.find((e) => e.id === id)?.name ??
        "Unavailable environment"
      : "Shared";
  const availability: { id: string | null; name: string }[] = current?.shared
    ? [{ id: null, name: "Shared" }]
    : catalog.environments.filter(
        (e) =>
          !current?.environment_ids?.length ||
          current.environment_ids.includes(e.id)
      );
  for (const c of credentials.filter((c) => !c.legacy_binding_id)) {
    if (!availability.some((env) => env.id === c.environment_id))
      availability.push({
        id: c.environment_id,
        name: environmentName(c.environment_id),
      });
  }
  function back() {
    setSelected(undefined);
    setUsage(undefined);
    setError("");
    setMode("detail");
  }
  async function addCredential(environmentId: string | null) {
    if (!current) return;
    setBusy(true);
    setError("");
    try {
      const c = await execute<AccessCredential>("/credentials", "POST", {
        resource_id: current.id,
        environment_id: environmentId,
        label: "",
        kind: current.credential_kind ?? "uri",
        fields: current.credential_fields ?? ["connection"],
        enabled: true,
      });
      setSelected(c);
      setMode("credential");
      onSaved();
    } catch (err) {
      onSaved();
      setError(accessError(err));
    } finally {
      setBusy(false);
    }
  }
  async function saveResource(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const list = aliases
      .split(",")
      .map((a) => a.trim())
      .filter(Boolean);
    const invalid = resourceError(name, list);
    if (invalid) {
      setError(invalid);
      return;
    }
    const fieldList = fields
      .split(",")
      .map((f) => f.trim())
      .filter(Boolean);
    if (
      !fieldList.length ||
      fieldList.length > 32 ||
      new Set(fieldList).size !== fieldList.length ||
      fieldList.some((f) => !/^[a-z][a-z0-9_]{0,63}$/.test(f))
    ) {
      setError(
        "Use 1–32 unique lowercase field names with letters, numbers or underscores."
      );
      return;
    }
    if (
      description.length > 4000 ||
      account.length > 120 ||
      region.length > 120
    ) {
      setError("Shorten the description or additional details.");
      return;
    }
    if (!shared && !envs.length) {
      setError("Choose at least one available environment.");
      return;
    }
    setBusy(true);
    try {
      await execute(
        current ? `/resources/${current.id}` : "/resources",
        current ? "PATCH" : "POST",
        {
          name: name.trim(),
          description,
          type,
          aliases: list,
          shared,
          environment_ids: shared ? [] : envs,
          credential_kind: kind,
          credential_fields: fieldList,
          account,
          region,
        }
      );
      onSaved();
      onClose();
    } catch (err) {
      setError(accessError(err));
    } finally {
      setBusy(false);
    }
  }
  if (mode === "legacy" && current)
    return (
      <LegacyResourceDialog
        root={root}
        catalog={catalog}
        resource={current}
        onClose={back}
        onSaved={onSaved}
      />
    );
  return (
    <Drawer
      anchor="right"
      open
      onClose={() => !busy && onClose()}
      className="access-drawer access-v2-drawer"
      slotProps={{
        paper: {
          role: "dialog",
          "aria-modal": true,
          "aria-labelledby": "access-resource-title",
        },
      }}
    >
      <Box className="access-drawer-shell">
        <Box className="access-drawer-header">
          <div className="access-drawer-title-row">
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="caption" color="text.secondary">
                Resources
              </Typography>
              <Typography id="access-resource-title" variant="h6">
                {current?.name ?? "Add a resource"}
              </Typography>
            </Box>
            <IconButton
              disabled={busy}
              aria-label="Close resource"
              onClick={onClose}
            >
              <CloseIcon />
            </IconButton>
          </div>
        </Box>
        <Box className="access-drawer-content">
          {error && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}
          {mode === "resource" && (
            <form
              className="access-form"
              onSubmit={(e) => void saveResource(e)}
              autoComplete="off"
            >
              <TextField
                label="Resource name"
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
                slotProps={{ htmlInput: { maxLength: 120 } }}
              />
              <TextField
                select
                label="Resource type"
                value={type}
                onChange={(e) =>
                  setType(e.target.value as AccessResource["type"])
                }
              >
                {["database", "observability", "cloud", "other"].map((t) => (
                  <MenuItem value={t} key={t}>
                    {t}
                  </MenuItem>
                ))}
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
                value={aliases}
                onChange={(e) => setAliases(e.target.value)}
                helperText="Comma-separated. Up to 20 aliases."
                slotProps={{ htmlInput: { maxLength: 2420 } }}
              />
              <TextField
                select
                label="Credential type"
                value={kind}
                onChange={(e) => {
                  const k = e.target.value as CredentialKind;
                  setKind(k);
                  setFields(defaults[k].join(", "));
                }}
              >
                {Object.entries(kindLabels).map(([k, label]) => (
                  <MenuItem key={k} value={k}>
                    {label}
                  </MenuItem>
                ))}
              </TextField>
              {kind === "fields" && (
                <TextField
                  required
                  label="Credential field names"
                  value={fields}
                  onChange={(e) => setFields(e.target.value)}
                  helperText="Comma-separated names, never credential values."
                />
              )}
              {kind === "ssh" && (
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={fields.includes("passphrase")}
                      onChange={(e) =>
                        setFields(
                          e.target.checked
                            ? "private_key, passphrase"
                            : "private_key"
                        )
                      }
                    />
                  }
                  label="Key requires a passphrase"
                />
              )}
              <FormControlLabel
                control={
                  <Checkbox
                    checked={shared}
                    onChange={(e) => setShared(e.target.checked)}
                  />
                }
                label="Shared across environments"
              />
              {!shared && (
                <fieldset className="access-environment-picker">
                  <legend>Available in</legend>
                  {catalog.environments.map((env) => (
                    <FormControlLabel
                      key={env.id}
                      control={
                        <Checkbox
                          checked={envs.includes(env.id)}
                          onChange={(e) =>
                            setEnvs((ids) =>
                              e.target.checked
                                ? [...ids, env.id]
                                : ids.filter((id) => id !== env.id)
                            )
                          }
                        />
                      }
                      label={env.name}
                    />
                  ))}
                  {!catalog.environments.length && (
                    <Typography variant="body2">
                      Create an environment in the Environments tab first.
                    </Typography>
                  )}
                </fieldset>
              )}
              <details className="access-additional-details">
                <summary>Additional details (optional)</summary>
                <div className="access-split-fields" style={{ marginTop: 16 }}>
                  <TextField
                    label="Account (optional)"
                    value={account}
                    onChange={(e) => setAccount(e.target.value)}
                    slotProps={{ htmlInput: { maxLength: 120 } }}
                  />
                  {kind !== "aws" && (
                    <TextField
                      label="Region (optional)"
                      value={region}
                      onChange={(e) => setRegion(e.target.value)}
                      slotProps={{ htmlInput: { maxLength: 120 } }}
                    />
                  )}
                  {kind === "aws" && (
                    <Typography variant="caption" color="text.secondary">
                      Set region per environment when adding its credential.
                    </Typography>
                  )}
                </div>
              </details>
              <div className="access-form-actions">
                <Button disabled={busy} onClick={current ? back : onClose}>
                  {current ? "Back" : "Cancel"}
                </Button>
                <Button type="submit" variant="contained" disabled={busy}>
                  {busy ? "Saving…" : "Save resource"}
                </Button>
              </div>
            </form>
          )}
          {mode === "credential" && selected && (
            <CredentialEditor
              key={selected.id}
              root={root}
              credential={selected}
              onSaved={onSaved}
              onBack={back}
            />
          )}
          {mode === "usage" && selected && (
            <UsageEditor
              key={usage?.id ?? selected.id}
              root={root}
              credential={selected}
              usage={usage}
              onSaved={onSaved}
              onBack={back}
            />
          )}
          {mode === "detail" && current && (
            <>
              <div className="access-resource-meta">
                <Typography variant="body2" color="text.secondary">
                  {current.description}
                </Typography>
                <Chip
                  size="small"
                  label={kindLabels[current.credential_kind ?? "fields"]}
                  variant="outlined"
                />
              </div>
              <Tabs
                value={tab}
                onChange={(_, v: number) => setTab(v)}
                variant="scrollable"
                scrollButtons="auto"
                aria-label="Resource sections"
                sx={{ mb: 3, borderBottom: 1, borderColor: "divider" }}
              >
                {["Credentials", "How to use", "Access"].map((label, i) => (
                  <Tab
                    key={label}
                    label={label}
                    id={`resource-tab-${i}`}
                    aria-controls={`resource-panel-${i}`}
                  />
                ))}
              </Tabs>
              <div
                role="tabpanel"
                id={`resource-panel-${tab}`}
                aria-labelledby={`resource-tab-${tab}`}
              >
                {tab === 0 && (
                  <>
                    <Typography
                      variant="body2"
                      color="text.secondary"
                      sx={{ mb: 2 }}
                    >
                      Store the credential once for each environment.
                      Applications can use it in different ways.
                    </Typography>
                    {availability.flatMap((env) => {
                      const instances = credentials.filter(
                        (c) =>
                          c.environment_id === env.id && !c.legacy_binding_id
                      );
                      return (instances.length ? instances : [undefined]).map(
                        (c) => (
                          <div
                            className="access-credential-row"
                            key={c?.id ?? env.id ?? "shared"}
                          >
                            <div className="access-credential-description">
                              <Typography fontWeight={600}>
                                {env.name}
                              </Typography>
                              {instances.length > 1 && (
                                <Typography
                                  variant="caption"
                                  display="block"
                                  color="text.secondary"
                                >
                                  Variant · {c?.label || c?.id}
                                </Typography>
                              )}
                              <Typography
                                variant="caption"
                                color="text.secondary"
                              >
                                {c?.has_secret
                                  ? c.credential_expires_at
                                    ? `Expires ${new Date(
                                        c.credential_expires_at
                                      ).toLocaleDateString()}`
                                    : "Stored in central vault"
                                  : "No credential yet"}
                              </Typography>
                            </div>
                            <Chip
                              className="access-credential-status"
                              size="small"
                              color={c?.has_secret ? "success" : "warning"}
                              variant="outlined"
                              label={
                                c?.pending_operation_id
                                  ? "Pending"
                                  : c?.has_secret
                                  ? "Stored"
                                  : "Missing"
                              }
                            />
                            <Button
                              className="access-credential-action"
                              variant={c?.has_secret ? "outlined" : "contained"}
                              aria-label={
                                instances.length > 1
                                  ? `${
                                      c?.has_secret
                                        ? "Replace"
                                        : "Add credential"
                                    } · ${c?.label || c?.id}`
                                  : undefined
                              }
                              disabled={busy}
                              onClick={() => {
                                if (c) {
                                  setSelected(c);
                                  setMode("credential");
                                } else void addCredential(env.id);
                              }}
                            >
                              {c?.has_secret ? "Replace" : "Add credential"}
                            </Button>
                          </div>
                        )
                      );
                    })}
                    {!availability.length && (
                      <Alert severity="info">
                        Add an environment or make this resource Shared.
                      </Alert>
                    )}
                    {credentials
                      .filter((c) => c.legacy_binding_id)
                      .map((c) => (
                        <div className="access-credential-row" key={c.id}>
                          <div className="access-credential-description">
                            <Typography fontWeight={600}>
                              {environmentName(c.environment_id)}
                            </Typography>
                            <Typography
                              variant="caption"
                              color="text.secondary"
                            >
                              Legacy variant · {c.label || c.legacy_binding_id}
                            </Typography>
                          </div>
                          <Chip
                            size="small"
                            label={c.has_secret ? "Stored" : "Missing"}
                          />
                          <Button
                            onClick={() => {
                              setSelected(c);
                              setMode("credential");
                            }}
                          >
                            Manage variant
                          </Button>
                        </div>
                      ))}
                    {legacy.length > 0 && (
                      <Button sx={{ mt: 2 }} onClick={() => setMode("legacy")}>
                        Manage legacy application mappings
                      </Button>
                    )}
                    <Button
                      sx={{ mt: 3, display: "block" }}
                      onClick={() => setMode("resource")}
                    >
                      Edit resource details
                    </Button>
                  </>
                )}
                {tab === 1 && (
                  <div className="access-form">
                    <Typography variant="body2" color="text.secondary">
                      Choose how each application receives fields from a
                      credential. Values stay in the vault.
                    </Typography>
                    {usages.map((u) => (
                      <div className="access-recipe-card" key={u.id}>
                        <Typography fontWeight={600}>{u.name}</Typography>
                        <Typography variant="body2" color="text.secondary">
                          {u.consumer} · {u.delivery.kind} ·{" "}
                          {environmentName(
                            credentials.find((c) => c.id === u.credential_id)
                              ?.environment_id ?? null
                          )}
                        </Typography>
                        <Button
                          onClick={() => {
                            setSelected(
                              credentials.find((c) => c.id === u.credential_id)
                            );
                            setUsage(u);
                            setMode("usage");
                          }}
                        >
                          Edit recipe
                        </Button>
                      </div>
                    ))}
                    {credentials.length ? (
                      <>
                        <TextField
                          select
                          label="Credential for new recipe"
                          value={selected?.id ?? ""}
                          onChange={(e) =>
                            setSelected(
                              credentials.find((c) => c.id === e.target.value)
                            )
                          }
                        >
                          <MenuItem value="">Choose credential</MenuItem>
                          {credentials.map((c) => (
                            <MenuItem key={c.id} value={c.id}>
                              {environmentName(c.environment_id)}
                              {c.legacy_binding_id
                                ? ` · Legacy ${c.label || c.id.slice(0, 8)}`
                                : ""}
                            </MenuItem>
                          ))}
                        </TextField>
                        <Button
                          variant="outlined"
                          disabled={!selected}
                          onClick={() => {
                            setUsage(undefined);
                            setMode("usage");
                          }}
                        >
                          Add usage recipe
                        </Button>
                      </>
                    ) : (
                      <Alert severity="info">
                        Add a credential in Credentials first. It can be
                        configured before its value is stored.
                      </Alert>
                    )}
                  </div>
                )}
                {tab === 2 && (
                  <UsageAccess
                    root={root}
                    catalog={catalog}
                    usages={usages}
                    credentials={credentials}
                    onSaved={onSaved}
                  />
                )}
              </div>
            </>
          )}
        </Box>
        {mode === "detail" && (
          <div className="access-drawer-footer">
            <Button onClick={onClose}>Done</Button>
          </div>
        )}
      </Box>
    </Drawer>
  );
}
