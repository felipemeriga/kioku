import {
  Button,
  Drawer,
  IconButton,
  Stack,
  useMediaQuery,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import { Link, useLocation } from "react-router-dom";
import { evidenceUrl, type EvidenceLocation } from "../../lib/agentEvidenceApi";
import PanelResizeHandle from "../PanelResizeHandle";
import { usePanelSize } from "../../hooks/usePanelSize";
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
  const mobile = useMediaQuery("(max-width:600px)");
  const panelSize = usePanelSize("originals", 680, 280, 1000, 72);
  return (
    <Drawer
      anchor="right"
      open={!!location}
      onClose={onClose}
      slotProps={{
        paper: {
          id: "original-evidence-panel",
          sx: {
            width: mobile ? "100%" : panelSize.size,
            maxWidth: "100%",
            p: 0,
            containerType: "inline-size",
          },
        },
      }}
    >
      {location && (
        <>
          {!mobile && (
            <PanelResizeHandle
              label="Resize original transcript"
              controls="original-evidence-panel"
              {...panelSize}
              onChange={panelSize.setSize}
              direction={-1}
              overlay
            />
          )}
          <Stack
            direction="row"
            justifyContent="flex-end"
            alignItems="center"
            gap={1}
            sx={{
              px: 2,
              py: 1,
              flexShrink: 0,
              "& .MuiButton-root": { whiteSpace: "normal", lineHeight: 1.4 },
            }}
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
