import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button, Typography } from "@mui/material";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import { ApiError } from "../../lib/api";
import {
  evidenceKeys,
  evidenceRetry,
  getJournalEvidence,
  type EvidenceLocation,
} from "../../lib/agentEvidenceApi";

export default function JournalEvidenceLink({
  folderId,
  entryId,
  timezone,
  onOpen,
}: {
  folderId: string;
  entryId: string;
  timezone: string;
  onOpen: (location: EvidenceLocation) => void;
}) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  return (
    <div className="evidence-entry-link">
      <Button
        size="small"
        sx={{ px: 0, minWidth: 0 }}
        disabled={pending}
        onClick={async () => {
          setPending(true);
          setMessage("");
          try {
            const result = await queryClient.fetchQuery({
              queryKey: evidenceKeys.entry(folderId, entryId),
              queryFn: ({ signal }) =>
                getJournalEvidence(folderId, entryId, signal),
              staleTime: 5000,
              retry: evidenceRetry,
            });
            if (
              (result.status === "available" ||
                result.status === "approximate") &&
              result.session_id
            ) {
              onOpen({
                folderId,
                sessionId: result.session_id,
                eventId: result.start_event_id,
                endEventId: result.end_event_id,
                timezone,
                mode: "conversation",
                approximate: result.status === "approximate",
              });
            } else
              setMessage(
                result.status === "pending"
                  ? "Original evidence is still syncing. The summary remains available."
                  : result.status === "deleted"
                  ? "Original evidence was deleted. This summary is retained."
                  : "Original evidence is unavailable for this entry."
              );
          } catch (error) {
            setMessage(
              error instanceof ApiError && error.status === 404
                ? "Original evidence is unavailable for this entry, or archival is not enabled yet."
                : "Could not resolve original evidence. Try again."
            );
          } finally {
            setPending(false);
          }
        }}
      >
        {pending ? "Finding evidence…" : "View evidence"}
      </Button>
      {message && (
        <div className="evidence-entry-feedback" role="status">
          <InfoOutlinedIcon
            aria-hidden="true"
            sx={{ fontSize: 16, mt: "2px" }}
          />
          <Typography variant="body2">{message}</Typography>
        </div>
      )}
    </div>
  );
}
