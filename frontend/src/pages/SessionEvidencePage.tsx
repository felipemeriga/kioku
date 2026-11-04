import {
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { Box, Button } from "@mui/material";
import TranscriptViewer from "../components/evidence/TranscriptViewer";
import { evidenceUrl, type EvidenceLocation } from "../lib/agentEvidenceApi";

export default function SessionEvidencePage() {
  const { folderId = "", sessionId = "" } = useParams();
  const [params] = useSearchParams();
  const route = useLocation();
  const navigate = useNavigate();
  let timezone =
    params.get("tz") ||
    Intl.DateTimeFormat().resolvedOptions().timeZone ||
    "UTC";
  try {
    new Intl.DateTimeFormat(undefined, { timeZone: timezone });
  } catch {
    timezone = "UTC";
  }
  const location: EvidenceLocation = {
    folderId,
    sessionId,
    eventId: params.get("event") || undefined,
    endEventId: params.get("end") || undefined,
    date: params.get("date") || undefined,
    mode: params.get("mode") === "raw" ? "raw" : "conversation",
    timezone,
    approximate: params.get("approx") === "1",
  };
  const state = route.state as { evidenceReturnTo?: string } | null;
  const returnTo = state?.evidenceReturnTo;
  return (
    <Box sx={{ p: { xs: 1.5, md: 3 } }}>
      <Button
        sx={{ mb: 2 }}
        onClick={() =>
          navigate(
            returnTo?.startsWith("/documents")
              ? returnTo
              : `/documents?folder=${encodeURIComponent(
                  folderId,
                )}&tab=learnings`,
          )
        }
      >
        ‹ Back to journal
      </Button>
      <TranscriptViewer
        key={`${folderId}:${sessionId}`}
        location={location}
        onLocationChange={(next) =>
          navigate(evidenceUrl(next), { state: route.state })
        }
      />
    </Box>
  );
}
