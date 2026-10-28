import { useSearchParams } from "react-router-dom";
import { useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Box,
  Typography,
  Button,
  Alert,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  TextField,
  Tooltip,
  Select,
  MenuItem,
  FormControl,
  Tab,
  Tabs,
  Skeleton,
} from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import { qk } from "../lib/queryKeys";
import {
  fetchApiKeys,
  createApiKey,
  revokeApiKey,
  fetchRootFolders,
  fetchUsageByConversation,
  fetchUsageByMonth,
} from "../lib/api";
import { NotionIntegrationSection } from "../components/NotionIntegrationSection";
import { messageFromError } from "../components/ToastProvider";
import { brand, fonts } from "../theme";

type SettingsTab = "api-keys" | "integrations" | "mcp-client" | "usage";
const fmtTokens = (n: number) => n.toLocaleString();
const fmtCost = (n: number) => `$${n.toFixed(n > 0 && n < 0.01 ? 4 : 2)}`;
const monthName = (month: string) =>
  new Date(`${month}-01T00:00:00Z`).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
const sectionTitle = { fontSize: 17, fontWeight: 600, lineHeight: 1.4, mb: 2 };
const inputStyle = {
  "& .MuiInputBase-root": {
    minHeight: 44,
    borderRadius: "4px",
    fontSize: 14,
    bgcolor: brand.ink,
  },
  "& input": { py: "11px" },
};

function SettingsPanel({
  title,
  description,
  action,
  children,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Box
      data-testid="settings-panel"
      sx={{
        width: "100%",
        maxWidth: 900,
        border: `1px solid ${brand.line}`,
        borderRadius: "8px",
        bgcolor: brand.surface,
        overflow: "hidden",
      }}
    >
      <Box
        sx={{
          p: "20px 24px",
          borderBottom: `1px solid ${brand.line}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 2,
          "@media(max-width:780px)": { p: "18px" },
        }}
      >
        <Box>
          <Typography
            component="h2"
            sx={{ fontSize: 21, fontWeight: 600, lineHeight: 1.3 }}
          >
            {title}
          </Typography>
          <Typography
            sx={{
              fontSize: 13,
              lineHeight: 1.55,
              color: brand.muted,
              mt: "5px",
            }}
          >
            {description}
          </Typography>
        </Box>
        {action}
      </Box>
      <Box sx={{ p: "24px", "@media(max-width:780px)": { p: "20px" } }}>
        {children}
      </Box>
    </Box>
  );
}

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const keysQuery = useQuery({ queryKey: qk.apiKeys(), queryFn: fetchApiKeys });
  const scopesQuery = useQuery({
    queryKey: ["root-folders"],
    queryFn: fetchRootFolders,
  });
  const usageByConv = useQuery({
    queryKey: qk.usageConversations(),
    queryFn: fetchUsageByConversation,
  });
  const usageByMonth = useQuery({
    queryKey: qk.usageMonthly(),
    queryFn: fetchUsageByMonth,
  });
  const keys = keysQuery.data ?? [];
  const scopes = scopesQuery.data ?? [];
  const loading = keysQuery.isPending || scopesQuery.isPending;
  const reloadKeys = () =>
    queryClient.invalidateQueries({ queryKey: qk.apiKeys() });
  const [newKey, setNewKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [configCopied, setConfigCopied] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedScope, setSelectedScope] = useState<string>("");
  const [keyName, setKeyName] = useState("Default");
  const [tabParams, setTabParams] = useSearchParams();
  const requestedTab = tabParams.get("tab");
  const activeTab: SettingsTab = [
    "api-keys",
    "integrations",
    "mcp-client",
    "usage",
  ].includes(requestedTab ?? "")
    ? (requestedTab as SettingsTab)
    : "api-keys";

  const handleGenerate = async () => {
    if (!selectedScope) {
      setError("Please select a scope.");
      return;
    }
    try {
      setError(null);
      const result = await createApiKey(keyName || "Default", selectedScope);
      setNewKey(result.key);
      await reloadKeys();
    } catch (err) {
      setError(`Couldn't generate API key: ${messageFromError(err)}`);
    }
  };

  const handleCopy = async () => {
    if (newKey) {
      try {
        await navigator.clipboard.writeText(newKey);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      } catch (err) {
        setError(
          `Couldn't copy — clipboard access denied. Copy the key manually: ${messageFromError(
            err,
          )}`,
        );
      }
    }
  };

  const handleRevoke = async () => {
    if (!revokeTarget) return;
    try {
      setError(null);
      await revokeApiKey(revokeTarget);
      await reloadKeys();
      setNewKey(null);
      setRevokeTarget(null);
    } catch (err) {
      setError(`Couldn't revoke API key: ${messageFromError(err)}`);
      setRevokeTarget(null);
    }
  };

  const monthly = usageByMonth.data ?? [];
  const conversations = usageByConv.data ?? [];
  const totalCost = monthly.reduce((sum, item) => sum + item.cost_usd, 0);
  const totalTokens = monthly.reduce(
    (sum, item) => sum + item.input_tokens + item.output_tokens,
    0,
  );
  const maxMonthCost = Math.max(0, ...monthly.map((item) => item.cost_usd));
  const local = ["localhost", "127.0.0.1", "::1"].includes(
    window.location.hostname,
  );
  const mcpUrl =
    import.meta.env.VITE_MCP_URL ||
    (local
      ? "http://localhost:8001/sse"
      : "https://kioku.mcp.merigafy.com/sse");
  const mcpConfig = JSON.stringify(
    {
      mcpServers: {
        kioku: {
          type: "sse",
          url: mcpUrl,
          headers: { Authorization: "Bearer YOUR_SCOPED_API_KEY" },
        },
      },
    },
    null,
    2,
  );
  const copyConfiguration = async () => {
    try {
      await navigator.clipboard.writeText(mcpConfig);
      setConfigCopied(true);
      window.setTimeout(() => setConfigCopied(false), 2000);
    } catch (err) {
      setError(`Couldn't copy configuration: ${messageFromError(err)}`);
    }
  };
  return (
    <Box
      data-testid="settings-page"
      sx={{
        width: "100%",
        maxWidth: 1280,
        mx: "auto",
        p: "36px 40px 56px",
        "@media(max-width:1150px)": { p: "30px" },
        "@media(max-width:780px)": { p: "26px 22px" },
        "@media(max-width:480px)": { p: "25px 18px 36px" },
      }}
    >
      <Box sx={{ mb: "28px" }}>
        <Typography
          component="h1"
          sx={{
            fontSize: 32,
            lineHeight: 1.2,
            fontWeight: 600,
            letterSpacing: "-0.8px",
            mb: "8px",
            "@media(max-width:480px)": { fontSize: 28 },
          }}
        >
          Settings
        </Typography>
        <Typography sx={{ fontSize: 16, lineHeight: 1.55, color: brand.muted }}>
          Manage scoped access, integrations, and usage.
        </Typography>
      </Box>
      <Tabs
        value={activeTab}
        onChange={(_, value: SettingsTab) => setTabParams({ tab: value })}
        sx={{
          mb: "26px",
          borderBottom: `1px solid ${brand.line}`,
          minHeight: 44,
          "& .MuiTabs-flexContainer": { gap: "28px" },
          "& .MuiTab-root": {
            p: "7px 0 12px",
            minWidth: 0,
            minHeight: 44,
            fontFamily: fonts.body,
            fontSize: 15,
            fontWeight: 500,
          },
          "& .Mui-selected": {
            background: "none",
            color: `${brand.text} !important`,
            boxShadow: "none",
            textShadow: "none",
          },
          "& .MuiTabs-indicator": { backgroundColor: brand.magenta, height: 2 },
        }}
      >
        <Tab value="api-keys" label="API keys" />
        <Tab value="integrations" label="Integrations" />
        <Tab value="mcp-client" label="MCP client" />
        <Tab value="usage" label="Usage" />
      </Tabs>
      {error && (
        <Alert
          severity="error"
          onClose={() => setError(null)}
          sx={{ maxWidth: 900, mb: 3 }}
        >
          {error}
        </Alert>
      )}
      {activeTab === "api-keys" && (
        <SettingsPanel
          title="MCP API keys"
          description="Give agents access to one root folder and its contents."
        >
          {keysQuery.isError && (
            <Alert
              severity="error"
              action={
                <Button onClick={() => void keysQuery.refetch()}>Retry</Button>
              }
              sx={{ mb: 2 }}
            >
              Couldn't load API keys: {messageFromError(keysQuery.error)}
            </Alert>
          )}
          {scopesQuery.isError && (
            <Alert
              severity="error"
              action={
                <Button onClick={() => void scopesQuery.refetch()}>
                  Retry
                </Button>
              }
              sx={{ mb: 2 }}
            >
              Couldn't load root folders: {messageFromError(scopesQuery.error)}
            </Alert>
          )}
          {newKey && (
            <Alert
              severity="warning"
              sx={{ mb: 3 }}
              action={
                <Tooltip title={copied ? "Copied!" : "Copy"}>
                  <IconButton
                    aria-label="Copy API key"
                    size="small"
                    onClick={handleCopy}
                  >
                    <ContentCopyIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              }
            >
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                Copy your API key now — it won't be shown again
              </Typography>
              <TextField
                fullWidth
                size="small"
                value={newKey}
                slotProps={{
                  input: { readOnly: true },
                  htmlInput: { "aria-label": "New API key" },
                }}
                sx={{
                  mt: 1,
                  "& input": { fontFamily: fonts.mono, fontSize: 13 },
                }}
              />
            </Alert>
          )}
          <Box
            data-testid="api-key-list"
            sx={{
              mb: "24px",
              pb: "24px",
              borderBottom: `1px solid ${brand.line}`,
            }}
          >
            {keysQuery.isPending ? (
              <Typography
                role="status"
                sx={{ color: brand.muted, fontSize: 14 }}
              >
                Loading API keys…
              </Typography>
            ) : !keysQuery.isError && keys.length === 0 ? (
              <Typography sx={{ color: brand.muted, fontSize: 14 }}>
                No API keys yet. Generate one for a root folder below.
              </Typography>
            ) : (
              keys.map((key, index) => (
                <Box
                  key={key.id}
                  sx={{
                    display: "flex",
                    justifyContent: "space-between",
                    gap: 2,
                    alignItems: "center",
                    py: "18px",
                    borderBottom:
                      index < keys.length - 1
                        ? `1px solid ${brand.line}`
                        : undefined,
                    "@media(max-width:480px)": { alignItems: "flex-start" },
                  }}
                >
                  <Box sx={{ minWidth: 0 }}>
                    <Typography
                      sx={{
                        fontSize: 17,
                        fontWeight: 600,
                        overflowWrap: "anywhere",
                      }}
                    >
                      {key.name}
                    </Typography>
                    <Typography
                      sx={{
                        fontSize: 13,
                        lineHeight: 1.55,
                        color: brand.muted,
                        mt: "5px",
                      }}
                    >
                      Key kept private · {key.scope_folder_name} scope
                    </Typography>
                    <Typography
                      sx={{
                        fontSize: 13,
                        lineHeight: 1.55,
                        color: brand.muted,
                        mt: "5px",
                      }}
                    >
                      Created {new Date(key.created_at).toLocaleDateString()}
                    </Typography>
                  </Box>
                  <Button
                    aria-label="Revoke key"
                    variant="outlined"
                    color="error"
                    onClick={() => setRevokeTarget(key.id)}
                    sx={{ minHeight: 44, flexShrink: 0 }}
                  >
                    Revoke
                  </Button>
                </Box>
              ))
            )}
          </Box>
          <Typography component="h3" sx={sectionTitle}>
            Generate a key
          </Typography>
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: "18px",
              "@media(max-width:780px)": { gridTemplateColumns: "1fr" },
            }}
          >
            <Box>
              <Typography
                component="label"
                htmlFor="kn"
                sx={{
                  display: "block",
                  fontSize: 14,
                  fontWeight: 500,
                  mb: "8px",
                }}
              >
                Key name
              </Typography>
              <TextField
                id="kn"
                value={keyName}
                onChange={(event) => setKeyName(event.target.value)}
                placeholder="e.g. Laptop coding tools"
                size="small"
                fullWidth
                sx={inputStyle}
              />
            </Box>
            <Box>
              <Typography
                component="label"
                htmlFor="sc"
                id="scope-label"
                sx={{
                  display: "block",
                  fontSize: 14,
                  fontWeight: 500,
                  mb: "8px",
                }}
              >
                Root folder
              </Typography>
              <FormControl fullWidth size="small">
                <Select
                  inputProps={{ id: "sc" }}
                  labelId="scope-label"
                  value={selectedScope}
                  onChange={(event) => setSelectedScope(event.target.value)}
                  displayEmpty
                  sx={{
                    minHeight: 44,
                    fontSize: 14,
                    bgcolor: brand.ink,
                    borderRadius: "4px",
                  }}
                >
                  <MenuItem value="" disabled>
                    Select a root folder
                  </MenuItem>
                  {scopes.map((scope) => (
                    <MenuItem key={scope.id} value={scope.id}>
                      {scope.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Box>
          </Box>
          <Typography
            sx={{ mt: "7px", mb: "22px", fontSize: 13, color: brand.muted }}
          >
            The new key is shown once. Store it somewhere safe.
          </Typography>
          <Button
            variant="contained"
            onClick={handleGenerate}
            disabled={loading || !selectedScope || scopesQuery.isError}
            sx={{ minHeight: 44 }}
          >
            Generate API key
          </Button>
          {scopes.length === 0 && !loading && !scopesQuery.isError && (
            <Alert severity="info" sx={{ mt: 2 }}>
              Create a root folder in Documents first — root folders serve as
              scopes for API keys.
            </Alert>
          )}
        </SettingsPanel>
      )}
      {activeTab === "integrations" && (
        <Box sx={{ maxWidth: 900 }}>
          <NotionIntegrationSection />
        </Box>
      )}
      {activeTab === "mcp-client" && (
        <SettingsPanel
          title="Connect MCP client"
          description="Use Kioku’s tools from your coding agent or another MCP client."
        >
          <Box
            sx={{
              p: "13px 16px",
              border: `1px solid ${brand.cyan}44`,
              bgcolor: `${brand.cyan}08`,
              borderRadius: "5px",
              mb: "24px",
              fontSize: 14,
              color: brand.muted,
            }}
          >
            For coding repositories,{" "}
            <Box
              component="code"
              sx={{ fontFamily: fonts.mono, color: brand.text }}
            >
              kioku init
            </Box>{" "}
            configures the connection automatically.
          </Box>
          <Typography
            component="label"
            htmlFor="mcp-server-url"
            sx={{ display: "block", fontSize: 14, fontWeight: 500, mb: "8px" }}
          >
            Server URL
          </Typography>
          <TextField
            id="mcp-server-url"
            fullWidth
            size="small"
            value={mcpUrl}
            slotProps={{ input: { readOnly: true } }}
            sx={{ ...inputStyle, mb: "22px" }}
          />
          <Typography sx={{ fontSize: 14, fontWeight: 500 }}>
            Example client configuration
          </Typography>
          <Box
            component="pre"
            sx={{
              m: "16px 0",
              p: "18px 20px",
              bgcolor: brand.ink,
              border: `1px solid ${brand.line}`,
              borderRadius: "5px",
              fontFamily: fonts.mono,
              fontSize: 13,
              lineHeight: 1.75,
              whiteSpace: "pre-wrap",
              overflowWrap: "anywhere",
              color: brand.text,
              "@media(max-width:480px)": { p: "14px", fontSize: 11 },
            }}
          >
            {mcpConfig}
          </Box>
          <Button
            variant="outlined"
            onClick={() => void copyConfiguration()}
            sx={{ minHeight: 44 }}
          >
            {configCopied ? "Copied configuration" : "Copy configuration"}
          </Button>
          <Box
            sx={{
              mt: "24px",
              pt: "24px",
              borderTop: `1px solid ${brand.line}`,
            }}
          >
            <Typography component="h3" sx={sectionTitle}>
              Available project tools
            </Typography>
            <Typography
              sx={{ color: brand.muted, fontSize: 14, lineHeight: 1.7 }}
            >
              Search documents and indexed code, load a folder briefing, and
              inspect definitions and references. Access is limited to the key’s
              folder scope.
            </Typography>
            <Typography sx={{ color: brand.muted, mt: 1, fontSize: 13 }}>
              This SSE configuration works with Claude Code. Codex uses the same
              server’s Streamable HTTP endpoint at{" "}
              <Box
                component="code"
                sx={{ fontFamily: fonts.mono, color: brand.text }}
              >
                {mcpUrl.replace(/\/sse\/?$/, "/mcp")}
              </Box>
              ;{" "}
              <Box component="code" sx={{ fontFamily: fonts.mono }}>
                kioku init
              </Box>{" "}
              writes the appropriate configuration.
            </Typography>
          </Box>
        </SettingsPanel>
      )}
      {activeTab === "usage" && (
        <SettingsPanel
          title="Usage"
          description="Estimated model usage across your conversations."
          action={
            <Typography
              sx={{ fontSize: 13, color: brand.muted, whiteSpace: "nowrap" }}
            >
              All recorded usage
            </Typography>
          }
        >
          {(usageByMonth.isError || usageByConv.isError) && (
            <Alert
              severity="error"
              sx={{ mb: 3 }}
              action={
                <Button
                  onClick={() => {
                    void usageByMonth.refetch();
                    void usageByConv.refetch();
                  }}
                >
                  Retry
                </Button>
              }
            >
              Couldn't load all usage data.{" "}
              {messageFromError(usageByMonth.error ?? usageByConv.error)}
            </Alert>
          )}
          <Box
            data-testid="usage-summary"
            sx={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr 1fr",
              gap: "30px",
              pb: "24px",
              mb: "24px",
              borderBottom: `1px solid ${brand.line}`,
              "@media(max-width:480px)": {
                gridTemplateColumns: "1fr 1fr",
                gap: "15px",
                "& > :last-child": { gridColumn: "1/-1" },
              },
            }}
          >
            {[
              {
                label: "Estimated cost",
                value:
                  usageByMonth.isPending || usageByMonth.isError
                    ? "—"
                    : fmtCost(totalCost),
                note: "Across recorded months",
              },
              {
                label: "Tokens",
                value:
                  usageByMonth.isPending || usageByMonth.isError
                    ? "—"
                    : fmtTokens(totalTokens),
                note: "Input and output combined",
              },
              {
                label: "Conversations",
                value:
                  usageByConv.isPending || usageByConv.isError
                    ? "—"
                    : conversations.length.toLocaleString(),
                note: "With recorded usage",
              },
            ].map((item) => (
              <Box key={item.label}>
                <Typography sx={{ fontSize: 13, color: brand.muted }}>
                  {item.label}
                </Typography>
                {(item.label === "Conversations" && usageByConv.isPending) ||
                (item.label !== "Conversations" && usageByMonth.isPending) ? (
                  <Skeleton
                    role="status"
                    aria-label={`Loading ${item.label.toLowerCase()}`}
                    width={95}
                    height={39}
                    sx={{ mt: "8px", mb: "2px" }}
                  />
                ) : (
                  <Typography
                    sx={{
                      fontSize: 30,
                      lineHeight: 1.3,
                      fontWeight: 500,
                      letterSpacing: "-0.6px",
                      mt: "8px",
                      mb: "2px",
                      "@media(max-width:780px)": { fontSize: 25 },
                    }}
                  >
                    {item.value}
                  </Typography>
                )}
                <Typography sx={{ fontSize: 13, color: brand.muted }}>
                  {item.note}
                </Typography>
              </Box>
            ))}
          </Box>
          <Typography component="h3" sx={sectionTitle}>
            By month
          </Typography>
          {usageByMonth.isPending ? (
            <Typography role="status" sx={{ color: brand.muted, fontSize: 14 }}>
              Loading monthly usage…
            </Typography>
          ) : monthly.length === 0 && !usageByMonth.isError ? (
            <Typography sx={{ color: brand.muted, fontSize: 14 }}>
              No usage recorded yet.
            </Typography>
          ) : (
            monthly.map((month) => (
              <Box
                key={month.month}
                sx={{
                  display: "flex",
                  gap: "18px",
                  alignItems: "center",
                  py: "13px",
                  fontSize: 14,
                }}
              >
                <Typography
                  sx={{
                    width: 90,
                    flexShrink: 0,
                    color: brand.muted,
                    fontSize: 14,
                  }}
                >
                  {monthName(month.month)}
                </Typography>
                <Box
                  role="img"
                  aria-label={`${monthName(month.month)}: ${fmtCost(
                    month.cost_usd,
                  )}`}
                  sx={{
                    flex: 1,
                    height: 7,
                    bgcolor: brand.ink,
                    borderRadius: "2px",
                    overflow: "hidden",
                  }}
                >
                  <Box
                    sx={{
                      height: "100%",
                      width: `${
                        maxMonthCost
                          ? (Math.max(0, month.cost_usd) / maxMonthCost) * 100
                          : 0
                      }%`,
                      bgcolor: brand.cyan,
                      borderRadius: "2px",
                    }}
                  />
                </Box>
                <Typography
                  sx={{ fontSize: 14, minWidth: 58, textAlign: "right" }}
                >
                  {fmtCost(month.cost_usd)}
                </Typography>
              </Box>
            ))
          )}
          <Typography component="h3" sx={{ ...sectionTitle, mt: "30px" }}>
            By conversation
          </Typography>
          {usageByConv.isPending ? (
            <Typography role="status" sx={{ color: brand.muted, fontSize: 14 }}>
              Loading conversation usage…
            </Typography>
          ) : conversations.length === 0 && !usageByConv.isError ? (
            <Typography sx={{ color: brand.muted, fontSize: 14 }}>
              No usage recorded yet.
            </Typography>
          ) : (
            <Box
              component="table"
              sx={{
                width: "100%",
                tableLayout: "fixed",
                borderCollapse: "collapse",
                "& th, & td": {
                  textAlign: "left",
                  py: "13px",
                  pr: "8px",
                  borderBottom: `1px solid ${brand.line}`,
                  fontSize: 14,
                  color: brand.muted,
                },
                "& th": { fontSize: 12, fontWeight: 500 },
                "& td:first-of-type": {
                  color: brand.text,
                  overflowWrap: "anywhere",
                },
                "& tr:last-child td": { borderBottom: 0 },
                "@media(max-width:480px)": { "& th, & td": { fontSize: 12 } },
              }}
            >
              <thead>
                <tr>
                  <th style={{ width: "65%" }}>Conversation</th>
                  <th>Tokens</th>
                  <th>Cost</th>
                </tr>
              </thead>
              <tbody>
                {conversations.map((conversation) => (
                  <tr key={conversation.conversation_id}>
                    <td>{conversation.title}</td>
                    <td>
                      {fmtTokens(
                        conversation.input_tokens + conversation.output_tokens,
                      )}
                    </td>
                    <td>{fmtCost(conversation.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </Box>
          )}
          <Typography sx={{ fontSize: 12, color: brand.muted, mt: "22px" }}>
            Costs are estimates based on recorded model tokens. Conversations
            without recorded usage are not included.
          </Typography>
        </SettingsPanel>
      )}
      <Dialog open={!!revokeTarget} onClose={() => setRevokeTarget(null)}>
        <DialogTitle>Revoke API Key</DialogTitle>
        <DialogContent>
          <DialogContentText>
            This will immediately disconnect any MCP clients using this key.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRevokeTarget(null)}>Cancel</Button>
          <Button onClick={handleRevoke} color="error" variant="contained">
            Revoke
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
