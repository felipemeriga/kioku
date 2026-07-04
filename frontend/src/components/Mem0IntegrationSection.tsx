import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import BoltIcon from "@mui/icons-material/Bolt";
import PsychologyIcon from "@mui/icons-material/Psychology";
import {
  connectMem0,
  disconnectMem0,
  fetchFolders,
  fetchMem0Configs,
  verifyMem0,
} from "../lib/api";
import type { Folder, Mem0Config } from "../lib/api";
import { messageFromError, useToast } from "./ToastProvider";

export function Mem0IntegrationSection() {
  const toast = useToast();
  const [configs, setConfigs] = useState<Mem0Config[]>([]);
  const [rootFolders, setRootFolders] = useState<Folder[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [disconnectTarget, setDisconnectTarget] = useState<Mem0Config | null>(
    null
  );
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const [cfgs, fs] = await Promise.all([
        fetchMem0Configs(),
        fetchFolders(null),
      ]);
      setConfigs(cfgs);
      setRootFolders(fs);
    } catch (err) {
      toast.showError(err, "Couldn't load Mem0 configs.");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleVerify = async (id: string) => {
    try {
      const r = await verifyMem0(id);
      if (r.ok) toast.showSuccess("Connection verified.");
      else toast.show(`Mem0 rejected the check: ${r.error}`, "warning");
      await refresh();
    } catch (err) {
      toast.showError(err, "Verify failed.");
    }
  };

  const handleDisconnect = async () => {
    if (!disconnectTarget) return;
    const { id } = disconnectTarget;
    setDisconnectTarget(null);
    try {
      await disconnectMem0(id);
      await refresh();
      toast.showSuccess("Mem0 disconnected.");
    } catch (err) {
      toast.showError(err, "Couldn't disconnect Mem0.");
    }
  };

  return (
    <Card sx={{ mb: 3 }}>
      <CardContent>
        <Stack
          direction="row"
          alignItems="center"
          justifyContent="space-between"
          mb={2}
        >
          <Stack direction="row" alignItems="center" spacing={1}>
            <PsychologyIcon fontSize="small" sx={{ color: "primary.main" }} />
            <Typography variant="h6">Mem0 Memory</Typography>
          </Stack>
          <Button variant="contained" onClick={() => setDialogOpen(true)}>
            Connect Mem0
          </Button>
        </Stack>

        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          Connect a folder to Mem0 for episodic and eternal memory. Eternal
          preferences are always inlined at session start; episodic memories are
          searchable via the MCP tools.
        </Typography>

        {!loading && configs.length === 0 && (
          <Typography color="text.secondary">
            No Mem0 integrations yet. Connect one to start capturing memory.
          </Typography>
        )}

        <Stack spacing={1.5}>
          {configs.map((cfg) => (
            <Box
              key={cfg.id}
              sx={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: 2,
                p: 1.5,
                border: 1,
                borderColor: "divider",
                borderRadius: 1,
              }}
            >
              <Box sx={{ minWidth: 0, flex: 1 }}>
                <Typography fontWeight="bold">
                  Folder: {cfg.root_folder_name}
                </Typography>
                <Typography variant="body2" color="text.secondary" noWrap>
                  {cfg.org_id ? `Org ${cfg.org_id} · ` : ""}
                  {cfg.project_id ? `Project ${cfg.project_id} · ` : ""}
                  {cfg.last_verified_at
                    ? `Verified ${new Date(cfg.last_verified_at).toLocaleString()}`
                    : "Never verified"}
                </Typography>
                {cfg.last_error && (
                  <Alert severity="warning" sx={{ mt: 1 }}>
                    {cfg.last_error}
                  </Alert>
                )}
              </Box>
              <Stack
                direction="row"
                spacing={1}
                sx={{
                  flexShrink: 0,
                  "& .MuiButton-root": { whiteSpace: "nowrap" },
                }}
              >
                <Button
                  startIcon={<BoltIcon />}
                  onClick={() => handleVerify(cfg.id)}
                >
                  Verify
                </Button>
                <Button
                  color="error"
                  startIcon={<DeleteIcon />}
                  onClick={() => setDisconnectTarget(cfg)}
                >
                  Disconnect
                </Button>
              </Stack>
            </Box>
          ))}
        </Stack>
      </CardContent>

      <Mem0ConnectDialog
        open={dialogOpen}
        rootFolders={rootFolders}
        onClose={() => setDialogOpen(false)}
        onConnected={async () => {
          setDialogOpen(false);
          await refresh();
          toast.showSuccess("Mem0 connected. Memory is now available.");
        }}
      />

      <Dialog
        open={!!disconnectTarget}
        onClose={() => setDisconnectTarget(null)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>Disconnect Mem0?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            This unlinks folder{" "}
            <strong>{disconnectTarget?.root_folder_name}</strong> from Mem0. The
            memories themselves stay in Mem0 — only the connection here is
            removed. You can reconnect later with the same API key.
          </DialogContentText>
        </DialogContent>
        <DialogActions sx={{ pr: 3, pb: 2 }}>
          <Button onClick={() => setDisconnectTarget(null)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={handleDisconnect}>
            Disconnect
          </Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
}

function Mem0ConnectDialog({
  open,
  rootFolders,
  onClose,
  onConnected,
}: {
  open: boolean;
  rootFolders: Folder[];
  onClose: () => void;
  onConnected: () => void;
}) {
  const [rootFolderId, setRootFolderId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [orgId, setOrgId] = useState("");
  const [projectId, setProjectId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      await connectMem0({
        root_folder_id: rootFolderId,
        api_key: apiKey,
        org_id: orgId || undefined,
        project_id: projectId || undefined,
      });
      onConnected();
      setApiKey("");
      setOrgId("");
      setProjectId("");
      setRootFolderId("");
    } catch (err) {
      setError(`Couldn't connect: ${messageFromError(err)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Connect Mem0</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <Typography variant="body2" color="text.secondary">
            1. Grab an API key at app.mem0.ai → Settings → API Keys. 2. Paste it
            below. 3. Select which folder this memory scope belongs to.
          </Typography>
          <TextField
            label="Mem0 API key"
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            type="password"
            fullWidth
          />
          <FormControl fullWidth>
            <InputLabel>Root folder</InputLabel>
            <Select
              value={rootFolderId}
              label="Root folder"
              onChange={(e) => setRootFolderId(e.target.value)}
            >
              {rootFolders.map((f) => (
                <MenuItem key={f.id} value={f.id}>
                  {f.name}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
          <Stack direction="row" spacing={2}>
            <TextField
              label="Org id (optional)"
              value={orgId}
              onChange={(e) => setOrgId(e.target.value)}
              fullWidth
            />
            <TextField
              label="Project id (optional)"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              fullWidth
            />
          </Stack>
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions sx={{ pr: 3, pb: 2 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          onClick={submit}
          disabled={!apiKey || !rootFolderId || busy}
        >
          {busy ? "Verifying…" : "Connect"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
