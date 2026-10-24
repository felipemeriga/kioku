import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { qk } from "../lib/queryKeys";
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
} from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import DeleteIcon from "@mui/icons-material/Delete";
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
import CornerCard from "../components/neo/CornerCard";
import { brand, fonts } from "../theme";

type SettingsTab = "api-keys" | "integrations" | "mcp-client" | "usage";

const fmtTokens = (n: number) => n.toLocaleString();
const fmtCost = (n: number) => `$${n.toFixed(4)}`;

function UsageTable({
  title,
  labelHeader,
  loading,
  rows,
}: {
  title: string;
  labelHeader: string;
  loading: boolean;
  rows: { key: string; label: string; tokens: number; cost: number }[];
}) {
  return (
    <Box>
      <Typography
        sx={{
          fontFamily: fonts.mono,
          fontSize: 12,
          color: brand.muted,
          letterSpacing: 0,
          mb: "8px",
        }}
      >
        {title}
      </Typography>
      {loading ? (
        <Typography sx={{ fontSize: 13, color: brand.muted }}>
          Loading…
        </Typography>
      ) : rows.length === 0 ? (
        <Typography sx={{ fontSize: 13, color: brand.muted }}>
          No usage recorded yet.
        </Typography>
      ) : (
        <Box
          component="table"
          sx={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}
        >
          <Box component="thead">
            <Box component="tr" sx={{ color: brand.muted }}>
              <Box
                component="th"
                sx={{ py: "6px", fontWeight: 500, textAlign: "left" }}
              >
                {labelHeader}
              </Box>
              <Box
                component="th"
                sx={{ py: "6px", fontWeight: 500, textAlign: "right" }}
              >
                Tokens
              </Box>
              <Box
                component="th"
                sx={{ py: "6px", fontWeight: 500, textAlign: "right" }}
              >
                Cost
              </Box>
            </Box>
          </Box>
          <Box component="tbody">
            {rows.map((r) => (
              <Box
                component="tr"
                key={r.key}
                sx={{ borderTop: `1px solid ${brand.line}` }}
              >
                <Box
                  component="td"
                  sx={{
                    py: "6px",
                    pr: "12px",
                    maxWidth: 320,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {r.label}
                </Box>
                <Box
                  component="td"
                  sx={{ py: "6px", textAlign: "right", fontFamily: fonts.mono }}
                >
                  {fmtTokens(r.tokens)}
                </Box>
                <Box
                  component="td"
                  sx={{
                    py: "6px",
                    textAlign: "right",
                    fontFamily: fonts.mono,
                    color: brand.cyan,
                  }}
                >
                  {fmtCost(r.cost)}
                </Box>
              </Box>
            ))}
          </Box>
        </Box>
      )}
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
  const [revokeTarget, setRevokeTarget] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedScope, setSelectedScope] = useState<string>("");
  const [keyName, setKeyName] = useState("Default");
  const [activeTab, setActiveTab] = useState<SettingsTab>("api-keys");

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
            err
          )}`
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

  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        flex: 1,
        p: { xs: "24px 20px", md: "40px 48px" },
        alignItems: "flex-start",
      }}
    >
      {/* Page header */}
      <Box sx={{ width: "100%", maxWidth: 960, mb: "22px" }}>
        <Typography
          sx={{
            fontFamily: fonts.mono,
            fontSize: 13,
            letterSpacing: 0,
            color: brand.muted,
            textTransform: "none",
          }}
        >
          Workspace
        </Typography>
        <Typography
          sx={{
            fontWeight: 700,
            fontSize: 34,
            lineHeight: 1.15,
            mt: "4px",
            letterSpacing: "-0.03em",
          }}
        >
          Settings
        </Typography>
        <Typography
          sx={{
            fontSize: 14,
            color: brand.muted,
            mt: "4px",
          }}
        >
          Manage MCP API keys, Notion syncs, and MCP client access.
        </Typography>
      </Box>

      <Box
        sx={{
          width: "100%",
          maxWidth: 960,
          display: "flex",
          flexDirection: "column",
          gap: "22px",
        }}
      >
        {error && (
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Tab navigation */}
        <Tabs
          value={activeTab}
          onChange={(_, v: SettingsTab) => setActiveTab(v)}
          sx={{
            borderBottom: `1px solid ${brand.line}`,
            "& .MuiTab-root": {
              color: brand.muted,
              fontWeight: 600,
              fontSize: 14,
              minHeight: 44,
              textTransform: "none",
              fontFamily: fonts.display,
            },
            "& .Mui-selected": {
              color: `${brand.cyan} !important`,
              background: `${brand.cyan}12`,
              boxShadow: `inset 0 -2px 0 ${brand.cyan}`,
            },
            "& .MuiTabs-indicator": { display: "none" },
          }}
        >
          <Tab value="api-keys" label="API Keys" />
          <Tab value="integrations" label="Integrations" />
          <Tab value="mcp-client" label="MCP Client" />
          <Tab value="usage" label="Usage" />
        </Tabs>

        {/* Tab: API Keys */}
        {activeTab === "api-keys" && (
          <CornerCard
            color={brand.magenta}
            sx={{
              p: "22px 24px",
              display: "flex",
              flexDirection: "column",
              gap: "14px",
            }}
          >
            {/* Section heading */}
            <Box sx={{ display: "flex", alignItems: "baseline", gap: "10px" }}>
              <Typography sx={{ fontSize: 19, fontWeight: 600, m: 0 }}>
                MCP API Keys
              </Typography>
            </Box>

            <Typography
              sx={{ fontSize: 14, lineHeight: 1.5, color: brand.muted, m: 0 }}
            >
              Generate API keys scoped to root folders. Each scope (e.g., Work,
              Personal) gets its own key for isolated MCP access.
            </Typography>

            {newKey && (
              <Alert
                severity="warning"
                action={
                  <Tooltip title={copied ? "Copied!" : "Copy"}>
                    <IconButton size="small" onClick={handleCopy}>
                      <ContentCopyIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                }
              >
                <Typography variant="body2" sx={{ fontWeight: 600, mb: 0.5 }}>
                  Copy your API key now — it won't be shown again
                </Typography>
                <TextField
                  fullWidth
                  size="small"
                  value={newKey}
                  slotProps={{ input: { readOnly: true } }}
                  sx={{
                    mt: 1,
                    "& .MuiInputBase-input": {
                      fontFamily: fonts.mono,
                      fontSize: "0.8rem",
                    },
                  }}
                />
              </Alert>
            )}

            {/* Key rows */}
            {keys.map((k) => (
              <Box
                key={k.id}
                sx={{
                  display: "flex",
                  alignItems: "center",
                  gap: "12px",
                  p: "12px 14px",
                  borderRadius: "4px",
                  border: `1px solid ${brand.lineGlow}`,
                  bgcolor: brand.surface2,
                }}
              >
                <Typography
                  sx={{
                    fontFamily: fonts.mono,
                    fontSize: 14,
                    color: brand.magenta,
                    textShadow: "none",
                    lineHeight: 1,
                  }}
                >
                  ⚿
                </Typography>
                <Typography sx={{ fontSize: 14, fontWeight: 500 }}>
                  {k.name}
                </Typography>
                <Box
                  component="span"
                  sx={{
                    px: "8px",
                    py: "2px",
                    borderRadius: "3px",
                    bgcolor: brand.magenta,
                    color: brand.ink,
                    fontFamily: fonts.mono,
                    fontSize: 13,
                    fontWeight: 600,
                  }}
                >
                  {k.scope_folder_name}
                </Box>
                <Box sx={{ flexGrow: 1 }} />
                <Typography
                  sx={{
                    fontFamily: fonts.mono,
                    fontSize: 12,
                    color: brand.muted,
                  }}
                >
                  {new Date(k.created_at).toLocaleDateString()}
                </Typography>
                <IconButton
                  size="small"
                  aria-label="Revoke key"
                  onClick={() => setRevokeTarget(k.id)}
                  sx={{
                    width: 30,
                    height: 30,
                    border: 0,
                    borderRadius: "3px",
                    color: brand.muted,
                    "&:hover": { color: brand.red },
                  }}
                >
                  <DeleteIcon sx={{ fontSize: 16 }} />
                </IconButton>
              </Box>
            ))}

            {/* Generate form row */}
            <Box
              sx={{
                display: "flex",
                flexWrap: "wrap",
                gap: "12px",
                alignItems: "flex-end",
              }}
            >
              <Box
                sx={{
                  flexGrow: 1,
                  display: "flex",
                  flexDirection: "column",
                  gap: "6px",
                }}
              >
                <Typography
                  component="label"
                  htmlFor="kn"
                  sx={{
                    fontFamily: fonts.mono,
                    fontSize: 13,
                    letterSpacing: 0,
                    color: brand.muted,
                    textTransform: "none",
                  }}
                >
                  KEY NAME
                </Typography>
                <TextField
                  id="kn"
                  size="small"
                  value={keyName}
                  onChange={(e) => setKeyName(e.target.value)}
                  sx={{
                    "& .MuiInputBase-root": {
                      height: 40,
                      borderRadius: "4px",
                      bgcolor: brand.surface2,
                      border: `1px solid ${brand.line}`,
                      color: brand.text,
                      fontSize: 14,
                    },
                  }}
                />
              </Box>
              <Box
                sx={{
                  width: 150,
                  display: "flex",
                  flexDirection: "column",
                  gap: "6px",
                }}
              >
                <Typography
                  component="label"
                  htmlFor="sc"
                  sx={{
                    fontFamily: fonts.mono,
                    fontSize: 13,
                    letterSpacing: 0,
                    color: brand.muted,
                    textTransform: "none",
                  }}
                >
                  SCOPE
                </Typography>
                <FormControl size="small">
                  <Select
                    inputProps={{ id: "sc" }}
                    value={selectedScope}
                    onChange={(e) => setSelectedScope(e.target.value)}
                    displayEmpty
                    sx={{
                      height: 40,
                      borderRadius: "4px",
                      bgcolor: brand.surface2,
                      border: `1px solid ${brand.line}`,
                      color: brand.muted,
                      fontSize: 14,
                    }}
                  >
                    <MenuItem value="" disabled>
                      Scope
                    </MenuItem>
                    {scopes.map((s) => (
                      <MenuItem key={s.id} value={s.id}>
                        {s.name}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Box>
              <Button
                onClick={handleGenerate}
                disabled={loading || !selectedScope}
                sx={{
                  height: 40,
                  px: "16px",
                  border: 0,
                  borderRadius: "4px",
                  backgroundColor: brand.magenta,
                  color: brand.ink,
                  fontWeight: 600,
                  fontSize: 14,
                  boxShadow: `0 4px 12px ${brand.magenta}44`,
                  textTransform: "none",
                  "&:hover": {
                    backgroundImage: `linear-gradient(90deg, ${brand.magenta} 0%, ${brand.purple} 100%)`,
                  },
                  "&.Mui-disabled": { opacity: 0.5 },
                }}
              >
                Generate
              </Button>
            </Box>

            {scopes.length === 0 && !loading && (
              <Alert severity="info">
                Create a root folder in Documents first — root folders serve as
                scopes for API keys.
              </Alert>
            )}
          </CornerCard>
        )}

        {/* Tab: Integrations */}
        {activeTab === "integrations" && <NotionIntegrationSection />}

        {/* Tab: MCP Client */}
        {activeTab === "mcp-client" && (
          <CornerCard
            color={brand.green}
            sx={{
              p: "22px 24px",
              display: "flex",
              flexDirection: "column",
              gap: "12px",
            }}
          >
            <Box sx={{ display: "flex", alignItems: "center", gap: "10px" }}>
              <Typography sx={{ fontSize: 19, fontWeight: 600, m: 0 }}>
                Connect MCP Client
              </Typography>
            </Box>

            <Typography sx={{ fontSize: 14, color: brand.muted, m: 0 }}>
              Add this to your MCP client configuration (e.g.,{" "}
              <Box
                component="code"
                sx={{ fontFamily: fonts.mono, color: brand.cyan }}
              >
                .mcp.json
              </Box>{" "}
              for Claude Code):
            </Typography>

            <Box
              component="pre"
              sx={{
                m: 0,
                p: "16px 18px",
                borderRadius: "4px",
                bgcolor: brand.inkDeep,
                border: `1px solid ${brand.line}`,
                fontFamily: fonts.mono,
                fontSize: 13,
                lineHeight: 1.6,
                color: brand.text,
                overflowX: "auto",
                whiteSpace: "pre",
              }}
            >
              {"{"}
              {"\n"}
              {"  "}
              <Box component="span" sx={{ color: brand.magentaGlow }}>
                "mcpServers"
              </Box>
              {": {\n    "}
              <Box component="span" sx={{ color: brand.magentaGlow }}>
                "kioku"
              </Box>
              {": {\n      "}
              <Box component="span" sx={{ color: brand.cyan }}>
                "type"
              </Box>
              {": "}
              <Box component="span" sx={{ color: brand.amber }}>
                "sse"
              </Box>
              {",\n      "}
              <Box component="span" sx={{ color: brand.cyan }}>
                "url"
              </Box>
              {": "}
              <Box component="span" sx={{ color: brand.amber }}>
                "http://localhost:8001/sse"
              </Box>
              {",\n      "}
              <Box component="span" sx={{ color: brand.cyan }}>
                "headers"
              </Box>
              {": { "}
              <Box component="span" sx={{ color: brand.cyan }}>
                "Authorization"
              </Box>
              {": "}
              <Box component="span" sx={{ color: brand.amber }}>
                {"Bearer <your-api-key>"}
              </Box>
              {" }\n    }\n  }\n}"}
            </Box>
          </CornerCard>
        )}

        {/* Tab: Usage */}
        {activeTab === "usage" && (
          <CornerCard
            color={brand.cyan}
            sx={{
              p: "22px 24px",
              display: "flex",
              flexDirection: "column",
              gap: "20px",
            }}
          >
            <Box>
              <Typography
                sx={{ fontSize: 19, fontWeight: 600, m: 0, mb: "4px" }}
              >
                Usage &amp; Cost
              </Typography>
              <Typography sx={{ fontSize: 13, color: brand.muted, m: 0 }}>
                Chat token usage and estimated cost. Tracked going forward; $
                figures are approximate.
              </Typography>
            </Box>

            <UsageTable
              title="BY MONTH"
              labelHeader="Month"
              loading={usageByMonth.isPending}
              rows={(usageByMonth.data ?? []).map((m) => ({
                key: m.month,
                label: m.month,
                tokens: m.input_tokens + m.output_tokens,
                cost: m.cost_usd,
              }))}
            />

            <UsageTable
              title="BY CONVERSATION"
              labelHeader="Conversation"
              loading={usageByConv.isPending}
              rows={(usageByConv.data ?? []).map((c) => ({
                key: c.conversation_id,
                label: c.title,
                tokens: c.input_tokens + c.output_tokens,
                cost: c.cost_usd,
              }))}
            />
          </CornerCard>
        )}
      </Box>

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
