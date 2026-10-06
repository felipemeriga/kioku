import { useState, useEffect, useCallback } from "react";
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
} from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
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
import { messageFromError } from "../components/ToastProvider";
import CornerCard from "../components/neo/CornerCard";
import { brand, fonts } from "../theme";

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
        p: "32px 40px",
        alignItems: "center",
      }}
    >
      {/* Page header */}
      <Box sx={{ width: 720, mb: "22px" }}>
        <Typography
          sx={{
            fontFamily: fonts.mono,
            fontSize: 11,
            letterSpacing: "0.3em",
            color: brand.muted,
            textTransform: "uppercase",
          }}
        >
          WORKSPACE
        </Typography>
        <Typography
          sx={{
            fontWeight: 700,
            fontSize: 34,
            lineHeight: 1.15,
            mt: "4px",
            textShadow: `0 0 18px ${brand.magenta}55`,
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
          Manage MCP keys, Notion sync, and workspace connections.
        </Typography>
      </Box>

      <Box
        sx={{
          width: 720,
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

        {/* 01 — MCP API Keys */}
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
            <Typography
              sx={{
                fontFamily: fonts.mono,
                fontSize: 12,
                color: brand.magenta,
              }}
            >
              01
            </Typography>
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
                  textShadow: `0 0 6px ${brand.magenta}`,
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
                  fontSize: 11,
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
          <Box sx={{ display: "flex", gap: "10px", alignItems: "flex-end" }}>
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
                  fontSize: 11,
                  letterSpacing: "0.2em",
                  color: brand.muted,
                  textTransform: "uppercase",
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
                  fontSize: 11,
                  letterSpacing: "0.2em",
                  color: brand.muted,
                  textTransform: "uppercase",
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
                backgroundImage: `linear-gradient(90deg, ${brand.magentaDeep} 0%, ${brand.purple} 100%)`,
                color: "#ffffff",
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

        {/* 02 — Notion Integration */}
        <NotionIntegrationSection />

        {/* 03 — Mem0 memory */}
        <Mem0IntegrationSection />

        {/* 04 — Connect MCP Client */}
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
            <Typography
              sx={{ fontFamily: fonts.mono, fontSize: 12, color: brand.green }}
            >
              04
            </Typography>
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
              "Bearer &lt;your-api-key&gt;"
            </Box>
            {" }\n    }\n  }\n}"}
          </Box>
        </CornerCard>
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
