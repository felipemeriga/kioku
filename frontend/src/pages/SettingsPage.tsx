import { useState, useEffect, useCallback } from "react";
import {
  Box,
  Typography,
  Button,
  Paper,
  Alert,
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions,
  TextField,
  alpha,
  Tooltip,
  Chip,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
} from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import KeyIcon from "@mui/icons-material/Key";
import DeleteIcon from "@mui/icons-material/Delete";
import {
  fetchApiKeys,
  createApiKey,
  revokeApiKey,
  fetchRootFolders,
  type ApiKeyInfo,
  type Folder,
} from "../lib/api";
import { NotionIntegrationSection } from "../components/NotionIntegrationSection";
import { Mem0IntegrationSection } from "../components/Mem0IntegrationSection";
import { GitHubIntegrationSection } from "../components/GitHubIntegrationSection";
import { messageFromError } from "../components/ToastProvider";

export default function SettingsPage() {
  const [keys, setKeys] = useState<ApiKeyInfo[]>([]);
  const [scopes, setScopes] = useState<Folder[]>([]);
  const [loading, setLoading] = useState(true);
  const [newKey, setNewKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [revokeTarget, setRevokeTarget] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedScope, setSelectedScope] = useState<string>("");
  const [keyName, setKeyName] = useState("Default");

  const loadData = useCallback(async () => {
    try {
      setError(null);
      const [keysData, scopesData] = await Promise.all([
        fetchApiKeys(),
        fetchRootFolders(),
      ]);
      setKeys(keysData);
      setScopes(scopesData);
    } catch (err) {
      setError(`Couldn't load settings: ${messageFromError(err)}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleGenerate = async () => {
    if (!selectedScope) {
      setError("Please select a scope.");
      return;
    }
    try {
      setError(null);
      const result = await createApiKey(keyName || "Default", selectedScope);
      setNewKey(result.key);
      await loadData();
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
          `Couldn't copy — clipboard access denied. Copy the key manually: ${messageFromError(err)}`,
        );
      }
    }
  };

  const handleRevoke = async () => {
    if (!revokeTarget) return;
    try {
      setError(null);
      await revokeApiKey(revokeTarget);
      setKeys((prev) => prev.filter((k) => k.id !== revokeTarget));
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
        p: 3,
      }}
    >
      <Box sx={{ mb: 3, maxWidth: 700, mx: "auto", width: "100%" }}>
        <Typography
          sx={{
            fontFamily: '"JetBrains Mono", monospace',
            fontSize: "0.64rem",
            letterSpacing: "0.28em",
            color: "text.secondary",
          }}
        >
          WORKSPACE
        </Typography>
        <Typography
          sx={{
            fontFamily: '"Space Grotesk", sans-serif',
            fontWeight: 700,
            fontSize: "1.75rem",
            letterSpacing: "-0.02em",
            lineHeight: 1.15,
            mt: 0.5,
          }}
        >
          Settings
        </Typography>
        <Typography
          sx={{
            fontFamily: '"Inter", sans-serif',
            fontSize: "0.9rem",
            color: "text.secondary",
            mt: 0.75,
          }}
        >
          Manage MCP keys, Notion sync, and workspace connections.
        </Typography>
      </Box>

      <Box sx={{ maxWidth: 700, mx: "auto", width: "100%" }}>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {/* Card 1: API Keys */}
        <Box
          sx={{
            bgcolor: alpha("#1e1e2e", 0.6),
            border: 1,
            borderColor: alpha("#ffffff", 0.06),
            borderRadius: 4,
            p: 3,
            mb: 3,
          }}
        >
          <Typography variant="h6" sx={{ mb: 2, fontWeight: 600 }}>
            MCP API Keys
          </Typography>
          <Typography
            variant="body2"
            sx={{ mb: 3, color: alpha("#ffffff", 0.6) }}
          >
            Generate API keys scoped to root folders. Each scope (e.g., Work,
            Personal) gets its own key for isolated MCP access.
          </Typography>

          {newKey && (
            <Alert
              severity="warning"
              sx={{ mb: 2 }}
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
                    fontFamily: "monospace",
                    fontSize: "0.8rem",
                  },
                }}
              />
            </Alert>
          )}

          {keys.map((k) => (
            <Paper
              key={k.id}
              sx={{
                p: 2,
                mb: 1,
                bgcolor: alpha("#ffffff", 0.03),
                border: 1,
                borderColor: alpha("#ffffff", 0.08),
              }}
            >
              <Box
                sx={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                }}
              >
                <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                  <KeyIcon sx={{ fontSize: 18, color: "#7c3aed" }} />
                  <Typography variant="body2" sx={{ fontWeight: 500 }}>
                    {k.name}
                  </Typography>
                  <Chip
                    label={k.scope_folder_name}
                    size="small"
                    color="primary"
                    sx={{ height: 20, fontSize: "0.7rem" }}
                  />
                </Box>
                <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
                  <Typography
                    variant="caption"
                    sx={{ color: alpha("#ffffff", 0.4) }}
                  >
                    {new Date(k.created_at).toLocaleDateString()}
                  </Typography>
                  <IconButton
                    size="small"
                    onClick={() => setRevokeTarget(k.id)}
                    sx={{ opacity: 0.4, "&:hover": { opacity: 1 } }}
                  >
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Box>
              </Box>
            </Paper>
          ))}

          <Box sx={{ display: "flex", gap: 1, mt: 2, alignItems: "flex-end" }}>
            <TextField
              label="Key name"
              size="small"
              value={keyName}
              onChange={(e) => setKeyName(e.target.value)}
              sx={{ flex: 1 }}
            />
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel>Scope</InputLabel>
              <Select
                value={selectedScope}
                label="Scope"
                onChange={(e) => setSelectedScope(e.target.value)}
              >
                {scopes.map((s) => (
                  <MenuItem key={s.id} value={s.id}>
                    {s.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <Button
              variant="contained"
              startIcon={<KeyIcon />}
              onClick={handleGenerate}
              disabled={loading || !selectedScope}
            >
              Generate
            </Button>
          </Box>

          {scopes.length === 0 && !loading && (
            <Alert severity="info" sx={{ mt: 2 }}>
              Create a root folder in Documents first — root folders serve as
              scopes for API keys.
            </Alert>
          )}
        </Box>

        <NotionIntegrationSection />

        <Mem0IntegrationSection />

        <GitHubIntegrationSection />

        {/* Card 2: MCP Configuration */}
        <Box
          sx={{
            bgcolor: alpha("#1e1e2e", 0.6),
            border: 1,
            borderColor: alpha("#ffffff", 0.06),
            borderRadius: 4,
            p: 3,
          }}
        >
          <Typography variant="h6" sx={{ mb: 2, fontWeight: 600 }}>
            Connect MCP Client
          </Typography>
          <Typography
            variant="body2"
            sx={{ mb: 2, color: alpha("#ffffff", 0.6) }}
          >
            Add this to your MCP client configuration (e.g.,{" "}
            <code>.mcp.json</code> for Claude Code):
          </Typography>
          <Paper
            sx={{
              p: 2,
              bgcolor: alpha("#000000", 0.3),
              border: 1,
              borderColor: alpha("#ffffff", 0.08),
              fontFamily: "monospace",
              fontSize: "0.8rem",
              whiteSpace: "pre",
              overflow: "auto",
            }}
          >
            {`{
  "mcpServers": {
    "agentic-rag": {
      "type": "sse",
      "url": "http://localhost:8001/sse",
      "headers": {
        "Authorization": "Bearer <your-api-key>"
      }
    }
  }
}`}
          </Paper>
        </Box>
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
