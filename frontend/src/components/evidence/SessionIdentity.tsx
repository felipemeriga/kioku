import { useState } from "react";
import { Button, Chip, Stack, Tooltip, Typography } from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import { fonts, brand } from "../../theme";

export default function SessionIdentity({
  agent,
  nativeId,
}: {
  agent: string;
  nativeId: string;
}) {
  const [message, setMessage] = useState("");
  return (
    <Stack direction="row" gap={1} alignItems="center" flexWrap="wrap">
      <Chip
        size="small"
        label={agent === "codex" ? "Codex" : "Claude Code"}
        variant="outlined"
      />
      <Tooltip title={`Session ID: ${nativeId}`}>
        <Button
          size="small"
          startIcon={<ContentCopyIcon sx={{ fontSize: 14 }} />}
          aria-label={`Copy session ID: ${nativeId}`}
          sx={{
            fontFamily: fonts.mono,
            color: brand.muted,
            fontSize: 12,
            overflowWrap: "anywhere",
          }}
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(nativeId);
              setMessage("Session ID copied.");
            } catch {
              setMessage(`Copy unavailable. Session ID: ${nativeId}`);
            }
          }}
        >
          Session{" "}
          {nativeId.length > 16
            ? `${nativeId.slice(0, 8)}…${nativeId.slice(-4)}`
            : nativeId}
        </Button>
      </Tooltip>
      <Typography component="span" role="status" sx={{ fontSize: 12 }}>
        {message}
      </Typography>
    </Stack>
  );
}
