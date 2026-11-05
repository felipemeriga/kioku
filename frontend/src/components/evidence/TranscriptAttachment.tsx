import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  CircularProgress,
  Stack,
  Typography,
} from "@mui/material";
import {
  downloadEvidence,
  getAttachmentMetadata,
  getAttachmentPreview,
  type EvidenceAttachment,
  type EvidenceLocation,
} from "../../lib/agentEvidenceApi";

export default function TranscriptAttachment({
  attachment,
  location,
}: {
  attachment: EvidenceAttachment;
  location: EvidenceLocation;
}) {
  const [open, setOpen] = useState(false);
  const [error, setError] = useState("");
  const metadata = useQuery({
    queryKey: [
      "evidence-attachment",
      location.folderId,
      location.sessionId,
      attachment.id,
    ],
    queryFn: ({ signal }) =>
      getAttachmentMetadata(location, attachment.id, signal),
    enabled: open,
    retry: 1,
  });
  const value = metadata.data ?? attachment;
  const empty = value.byte_length === 0;
  const text =
    !value.content_type ||
    /^(text\/|application\/(json|x-ndjson))/.test(value.content_type);
  const preview = useQuery({
    queryKey: [
      "evidence-attachment-preview",
      location.folderId,
      location.sessionId,
      attachment.id,
    ],
    queryFn: ({ signal }) =>
      getAttachmentPreview(location, attachment.id, signal),
    enabled: open && !!metadata.data && value.available && text && !empty,
    retry: 1,
  });
  return (
    <section
      className="evidence-attachment"
      aria-label={`Attachment ${value.original_name}`}
    >
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        flexWrap="wrap"
        gap={1}
      >
        <Typography sx={{ fontSize: 13 }}>
          {value.original_name} ·{" "}
          {new Intl.NumberFormat().format(value.byte_length)} bytes
        </Typography>
        <Button
          size="small"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
        >
          {open ? "Close preview" : "Preview attachment"}
        </Button>
      </Stack>
      {open && (
        <>
          {metadata.isLoading && (
            <CircularProgress size={18} aria-label="Loading attachment" />
          )}
          {metadata.isError && (
            <Alert
              severity="error"
              action={
                <Button onClick={() => void metadata.refetch()}>Retry</Button>
              }
            >
              Could not load attachment metadata.
            </Alert>
          )}
          {!value.available && (
            <Alert severity="warning">
              The referenced attachment is missing.
            </Alert>
          )}
          {preview.isLoading && (
            <Typography>Loading attachment preview…</Typography>
          )}
          {preview.isError && (
            <Alert
              severity="error"
              action={
                <Button onClick={() => void preview.refetch()}>Retry</Button>
              }
            >
              Could not load attachment preview.
            </Alert>
          )}
          {preview.data !== undefined && (
            <>
              <pre className="evidence-pre">{preview.data}</pre>
              <Typography variant="caption">
                Preview limited to 64 KiB. Download retains the archived bytes.
              </Typography>
            </>
          )}
          {value.available && empty && (
            <Typography variant="body2">Empty attachment (0 bytes).</Typography>
          )}
          {!text && !empty && (
            <Typography variant="body2">
              Binary attachment. Download to inspect its original bytes.
            </Typography>
          )}
          {value.available && (
            <Button
              size="small"
              onClick={() =>
                void downloadEvidence(
                  location,
                  "attachment",
                  attachment.id
                ).catch(() => setError("Could not download the attachment."))
              }
            >
              Download attachment
            </Button>
          )}
          {error && <Alert severity="error">{error}</Alert>}
        </>
      )}
    </section>
  );
}
