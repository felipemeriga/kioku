import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Button,
  CircularProgress,
  IconButton,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from "@mui/material";
import DownloadOutlinedIcon from "@mui/icons-material/DownloadOutlined";
import ContentCopyOutlinedIcon from "@mui/icons-material/ContentCopyOutlined";
import {
  downloadEvidence,
  getEvidenceContent,
  type EvidenceEvent,
  type EvidenceLocation,
  type EvidencePresentation,
  type RawEvidenceRecord,
} from "../../lib/agentEvidenceApi";
import { ReadableContent } from "../agent-evidence/ReadableContent";
import TranscriptAttachment from "./TranscriptAttachment";
import { prettyJsonSource } from "../agent-evidence/contentBlocks";

function RecordActions({
  location,
  eventId,
  available = true,
  text,
  copyLabel = "Copy archived preview",
}: {
  location: EvidenceLocation;
  eventId: string;
  available?: boolean;
  text: string;
  copyLabel?: string;
}) {
  const [error, setError] = useState("");
  const copy = async () => {
    try {
      if (!navigator.clipboard) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(text);
    } catch {
      setError("Could not copy the displayed content.");
    }
  };
  return (
    <>
      <Stack direction="row" gap={0.5}>
        <Tooltip title={copyLabel}>
          <IconButton
            size="small"
            aria-label={copyLabel}
            disabled={!text}
            onClick={() => void copy()}
          >
            <ContentCopyOutlinedIcon fontSize="small" />
          </IconButton>
        </Tooltip>
        {available && (
          <Tooltip title="Download original record">
            <IconButton
              size="small"
              aria-label="Download original record"
              onClick={() =>
                void downloadEvidence(location, "raw", eventId).catch(() =>
                  setError("Could not download this source record."),
                )
              }
            >
              <DownloadOutlinedIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        )}
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}
    </>
  );
}
function PresentedContent({
  presentation,
  text,
  complete,
  tool = false,
}: {
  presentation?: EvidencePresentation;
  text: string;
  complete: boolean;
  tool?: boolean;
}) {
  if (!presentation?.blocks.length)
    return (
      <ReadableContent
        text={text}
        kind={tool ? "terminal" : "markdown"}
        complete={complete}
      />
    );
  const command = presentation.tool?.command_text;
  const showCommand =
    command &&
    !presentation.blocks.some((block) => block.text.trim() === command.trim());
  return (
    <>
      {showCommand && (
        <div className="evidence-command">
          <Typography variant="caption">Command</Typography>
          <ReadableContent
            text={command}
            kind="code"
            language="bash"
            complete={!presentation.source_truncated}
          />
        </div>
      )}
      {presentation.blocks.map((block, index) => (
        <ReadableContent
          key={index}
          {...block}
          complete={
            !(block.viewer_truncated ?? presentation.viewer_truncated) &&
            !presentation.source_truncated
          }
        />
      ))}
    </>
  );
}
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
          <PresentedContent
            presentation={
              offset === 0 && !content.data.has_more
                ? content.data.presentation
                : undefined
            }
            text={content.data.content}
            complete={
              offset === 0 &&
              !content.data.has_more &&
              !content.data.viewer_truncated
            }
          />
          {(offset > 0 ||
            content.data.viewer_truncated ||
            content.data.has_more) && (
            <Typography variant="caption">
              Showing a bounded portion of archived content. Partial portions
              remain faithful text.
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
  const [format, setFormat] = useState("formatted");
  let parsed: string | undefined;
  if (
    record.raw_encoding === "utf-8" &&
    !record.viewer_truncated &&
    record.raw_text !== null &&
    new TextEncoder().encode(record.raw_text).byteLength === record.byte_length
  ) {
    parsed = prettyJsonSource(record.raw_text);
  }
  return (
    <article
      className={`evidence-event${selected ? " evidence-selected" : ""}`}
      data-event-id={record.event_id}
    >
      <Stack
        direction="row"
        justifyContent="space-between"
        alignItems="center"
        flexWrap="wrap"
        gap={1}
      >
        <div className="evidence-source">
          Record {record.source.record_sequence} · {record.byte_length} bytes
        </div>
        <RecordActions
          location={location}
          eventId={record.event_id}
          text={record.raw_text ?? ""}
          copyLabel={
            !record.viewer_truncated &&
            record.raw_text !== null &&
            new TextEncoder().encode(record.raw_text).byteLength ===
              record.byte_length
              ? "Copy source record"
              : "Copy source preview"
          }
        />
      </Stack>
      {parsed !== undefined && (
        <ToggleButtonGroup
          size="small"
          exclusive
          value={format}
          aria-label="Raw record presentation"
          onChange={(_, next) => next && setFormat(next)}
        >
          <ToggleButton value="formatted">Formatted</ToggleButton>
          <ToggleButton value="source">Source</ToggleButton>
        </ToggleButtonGroup>
      )}
      {record.raw_encoding === "base64" ? (
        <Typography>
          Binary/unreadable source encoding. Download the exact original bytes.
        </Typography>
      ) : parsed !== undefined && format === "formatted" ? (
        <ReadableContent text={parsed} kind="code" language="json" />
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
      {parsed !== undefined && (
        <Typography variant="caption">
          Formatting changes presentation only. Source, copy and download retain
          the original record.
        </Typography>
      )}
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
  const tool = /tool|function/.test(event.event_type) || event.role === "tool";
  const metadata = event.presentation?.tool;
  const label = tool
    ? metadata?.name || "Tool activity"
    : event.role === "user"
    ? "You"
    : event.role === "assistant"
    ? "Agent"
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
      }${tool ? " evidence-tool" : ""}`}
      data-event-id={event.event_id}
    >
      {selected && (
        <div className="evidence-linked">Selected source evidence</div>
      )}
      <Stack
        direction="row"
        justifyContent="space-between"
        gap={1}
        alignItems="center"
      >
        <Typography sx={{ fontSize: 13, fontWeight: 600 }}>{label}</Typography>
        <Stack direction="row" alignItems="center" gap={1}>
          <Typography component="time" variant="caption">
            {time}
          </Typography>
          <RecordActions
            location={location}
            eventId={event.event_id}
            available={event.raw_available}
            text={event.content_preview}
          />
        </Stack>
      </Stack>
      {event.inherited && (
        <Typography variant="caption">
          Inherited parent context · not new child execution
        </Typography>
      )}
      <PresentedContent
        presentation={event.presentation}
        text={event.content_preview}
        complete={!event.viewer_truncated && !event.source_truncated}
        tool={tool}
      />
      {metadata && (
        <div className="evidence-tool-metadata">
          {metadata.status && (
            <span>
              {metadata.status === "completed" ? "Completed" : metadata.status}
            </span>
          )}
          {metadata.exit_code !== undefined && (
            <span>Exit {metadata.exit_code}</span>
          )}
          {metadata.duration_seconds !== undefined && (
            <span>
              Command{" "}
              {metadata.duration_seconds.toLocaleString(undefined, {
                maximumFractionDigits: 3,
              })}{" "}
              s
            </span>
          )}
          {metadata.orchestration_seconds !== undefined && (
            <span>
              Orchestration{" "}
              {metadata.orchestration_seconds.toLocaleString(undefined, {
                maximumFractionDigits: 3,
              })}{" "}
              s
            </span>
          )}
        </div>
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
      {event.attachments.map((attachment) => (
        <TranscriptAttachment
          key={attachment.id}
          attachment={attachment}
          location={location}
        />
      ))}
      <details className="evidence-source-details">
        <summary>
          Source details · record {event.source.record_sequence}
        </summary>
        <div className="evidence-source">
          {event.event_type} · Stream {event.source.stream_id} · Generation{" "}
          {event.source.generation}
        </div>
        {metadata?.cwd && (
          <div className="evidence-source">
            Working directory {metadata.cwd}
          </div>
        )}
        {event.call_id && (
          <div className="evidence-source">
            Call {event.call_id}
            {linkedCall
              ? " · matching native call/result in this day window"
              : tool
              ? " · matching call/result outside this window or unavailable"
              : ""}
          </div>
        )}
      </details>
    </article>
  );
}
