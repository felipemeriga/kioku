import { Button, Drawer, IconButton, Stack } from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import { Link, useLocation } from "react-router-dom";
import { evidenceUrl, type EvidenceLocation } from "../../lib/agentEvidenceApi";
import TranscriptViewer from "./TranscriptViewer";

export default function EvidenceDrawer({
  location,
  onLocationChange,
  onClose,
}: {
  location: EvidenceLocation | null;
  onLocationChange: (location: EvidenceLocation) => void;
  onClose: () => void;
}) {
  const route = useLocation();
  return (
    <Drawer
      anchor="right"
      open={!!location}
      onClose={onClose}
      slotProps={{
        paper: {
          sx: { width: { xs: "100%", sm: 680 }, maxWidth: "100%", p: 0 },
        },
      }}
    >
      {location && (
        <>
          <Stack
            direction="row"
            justifyContent="flex-end"
            alignItems="center"
            gap={1}
            sx={{ px: 2, py: 1 }}
          >
            <Button
              component={Link}
              to={evidenceUrl(location)}
              state={{ evidenceReturnTo: route.pathname + route.search }}
            >
              Open full transcript
            </Button>
            <IconButton aria-label="Close evidence" onClick={onClose}>
              <CloseIcon />
            </IconButton>
          </Stack>
          <TranscriptViewer
            key={`${location.folderId}:${location.sessionId}`}
            location={location}
            onLocationChange={onLocationChange}
            variant="drawer"
          />
        </>
      )}
    </Drawer>
  );
}
