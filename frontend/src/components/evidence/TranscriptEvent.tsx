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
  getEvidenceContent,
  type EvidenceEvent,
  type EvidenceLocation,
  type RawEvidenceRecord,
} from "../../lib/agentEvidenceApi";
import TranscriptAttachment from "./TranscriptAttachment";

function ExpandedContent({
  eventId,
  location,
}: {
  eventId: string;
  location: EvidenceLocation;
}) {
  const [offset, setOffset] = useState(0);
  const content = useQuery({
    queryKey: [
      "evidence-event-content",
      location.folderId,
      location.sessionId,
      eventId,
      offset,
    ],
    queryFn: ({ signal }) =>
      getEvidenceContent(location, eventId, offset, signal),
    retry: 1,
  });
  return (
    <>
      {content.isLoading && (
        <CircularProgress size={16} aria-label="Loading original content" />
      )}
      {content.isError && (
        <Alert
          severity="error"
          action={<Button onClick={() => void content.refetch()}>Retry</Button>}
        >
          Could not load event content.
        </Alert>
      )}
      {content.data && (
        <>
          <pre className="evidence-pre">{content.data.content}</pre>
          {content.data.viewer_truncated && (
            <Typography variant="caption">
              Showing a bounded portion of the archived content.
            </Typography>
          )}
          <Stack direction="row" gap={1}>
            {offset > 0 && (
              <Button size="small" onClick={() => setOffset(0)}>
                Back to beginning
              </Button>
            )}
            {content.data.has_more &&
              content.data.next_offset !== undefined && (
                <Button
                  size="small"
                  onClick={() => setOffset(content.data!.next_offset!)}
                >
                  Next content portion
                </Button>
              )}
          </Stack>
        </>
      )}
    </>
  );
}

export function RawTranscriptRecord({
  record,
  location,
  selected = false,
}: {
  record: RawEvidenceRecord;
  location: EvidenceLocation;
  selected?: boolean;
}) {
  const [error, setError] = useState("");
  return (
    <article
      className={`evidence-event${selected ? " evidence-selected" : ""}`}
      data-event-id={record.event_id}
    >
      <div className="evidence-source">
        Record {record.source.record_sequence} · {record.byte_length} bytes
      </div>
      {record.raw_encoding === "base64" ? (
        <Typography>
          Binary/unreadable source encoding. Download the exact original bytes.
        </Typography>
      ) : (
        <pre className="evidence-pre">
          {record.raw_text ?? "Source content is not available in this window."}
        </pre>
      )}
      {record.viewer_truncated && (
        <Typography variant="caption">
          Viewer preview only; the archived record is larger.
        </Typography>
      )}
      <Button
        size="small"
        onClick={() =>
          void downloadEvidence(location, "raw", record.event_id).catch(() =>
            setError("Could not download this source record."),
          )
        }
      >
        Download original record
      </Button>
      {error && <Alert severity="error">{error}</Alert>}
    </article>
  );
}

export default function TranscriptEvent({
  event,
  location,
  selected,
  onChild,
  linkedCall,
}: {
  event: EvidenceEvent;
  location: EvidenceLocation;
  selected: boolean;
  onChild: (id: string) => void;
  linkedCall?: string;
}) {
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState("");
  const tool = /tool|function/.test(event.event_type) || event.role === "tool";
  const label =
    event.role === "user"
      ? "You"
      : event.role === "assistant"
      ? "Agent"
      : event.role === "tool" || tool
      ? "Tool activity"
      : "Session event";
  const time = event.event_at
    ? new Intl.DateTimeFormat(undefined, {
        timeZone: location.timezone,
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date(event.event_at))
    : "Time unknown";
  return (
    <article
      className={`evidence-event${selected ? " evidence-selected" : ""}${
        event.role === "user" ? " evidence-user" : ""
      }`}
      data-event-id={event.event_id}
    >
      {selected && (
        <div className="evidence-linked">Source linked from your journal</div>
      )}
      <Stack direction="row" justifyContent="space-between" gap={1}>
        <Typography sx={{ fontSize: 13, fontWeight: 600 }}>{label}</Typography>
        <Typography component="time" variant="caption">
          {time}
        </Typography>
      </Stack>
      {event.inherited && (
        <Typography variant="caption">
          Inherited parent context · not new child execution
        </Typography>
      )}
      <Typography className="evidence-content" component="div">
        {event.content_preview}
      </Typography>
      {event.call_id && (
        <Typography className="evidence-source">
          Call {event.call_id}
          {linkedCall
            ? " · matching call/result in loaded window"
            : tool
            ? " · matching call/result outside this window or unavailable"
            : ""}
        </Typography>
      )}
      {event.source_truncated && (
        <Alert severity="warning">
          This output was truncated before capture.{" "}
          {event.attachments.some((attachment) => attachment.available)
            ? "An archived attachment is available below; inspect it for the complete output."
            : "No complete archived attachment is available in this event."}
        </Alert>
      )}
      {event.viewer_truncated && (
        <Typography variant="caption">
          This is a bounded viewer preview.
        </Typography>
      )}
      {(tool || event.viewer_truncated) && (
        <Button
          size="small"
          aria-expanded={expanded}
          onClick={() => setExpanded(!expanded)}
        >
          {expanded ? "Collapse content" : "Expand content"}
        </Button>
      )}
      {expanded && (
        <ExpandedContent eventId={event.event_id} location={location} />
      )}
      {event.child_session_id && (
        <Button size="small" onClick={() => onChild(event.child_session_id!)}>
          View child evidence
        </Button>
      )}
      {(event.attachments ?? []).map((attachment) => (
        <TranscriptAttachment
          key={attachment.id}
          attachment={attachment}
          location={location}
        />
      ))}
      <div className="evidence-source">
        Record {event.source.record_sequence} · {event.event_type}
      </div>
      {event.raw_available && (
        <Button
          size="small"
          onClick={() =>
            void downloadEvidence(location, "raw", event.event_id).catch(() =>
              setError("Could not download this source record."),
            )
          }
        >
          Download original record
        </Button>
      )}
      {error && <Alert severity="error">{error}</Alert>}
    </article>
  );
}
