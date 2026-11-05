import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "../../test/renderWithProviders";
import * as api from "../../lib/api";
import { ApiError } from "../../lib/api";
import {
  type EvidenceLocation,
  type EvidenceSession,
} from "../../lib/agentEvidenceApi";
import TranscriptViewer from "./TranscriptViewer";
import JournalEvidenceLink from "./JournalEvidenceLink";
import TranscriptAttachment from "./TranscriptAttachment";

vi.mock("../../lib/supabase", () => ({
  supabase: { auth: { getSession: vi.fn() } },
}));
const location: EvidenceLocation = {
  folderId: "repo",
  sessionId: "parent",
  timezone: "UTC",
  mode: "conversation",
  eventId: "event-1",
};
const nativeId = "8dd720ab-0182-46f2-a6eb-bcc000d4f48f";
const session: EvidenceSession = {
  id: "parent",
  agent: "claude_code",
  native_session_id: nativeId,
  parent_session_id: null,
  root_session_id: "parent",
  title: "Verify invoice",
  first_event_at: "2026-11-04T23:59:00Z",
  last_event_at: "2026-12-03T10:00:00Z",
  manifest_revision: 4,
  indexed_revision: 4,
  capture_status: "captured",
  index_status: "ready",
  event_count: 9000,
  active_day_count: 8,
  children: [
    {
      id: "child",
      agent: "claude_code",
      native_session_id: "opaque-child",
      event_count: 3,
    },
  ],
  gaps: [],
};
const event = {
  event_id: "event-1",
  role: "tool",
  event_type: "tool_result",
  event_at: "2026-11-04T23:59:00Z",
  content_preview: "fixture total31 <script>not executable</script>",
  raw_available: true,
  viewer_truncated: true,
  source_truncated: true,
  child_session_id: "child",
  call_id: "call-one",
  attachments: [
    {
      id: "blob",
      original_name: "output.txt",
      byte_length: 70031,
      available: true,
    },
  ],
  source: {
    object_id: "segment-one",
    stream_id: "stream",
    generation: 1,
    record_sequence: 20,
  },
};
function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}
describe("shared original transcript reader", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "apiFetch").mockImplementation(async (path) => {
      const url = String(path);
      if (url.endsWith("/parent")) return response(session);
      if (url.includes("/days"))
        return response({
          days: [
            {
              date: "2026-11-04",
              turn_count: 2,
              event_count: 4,
              first_event_id: "event-1",
            },
            {
              date: "2026-12-03",
              turn_count: 3,
              event_count: 8,
              first_event_id: "last-event",
            },
          ],
          timezone: "UTC",
        });
      if (url.includes("/events?"))
        return response({
          events: [event],
          previous_cursor: "older",
          next_cursor: "newer",
          snapshot_revision: 4,
          status: "ok",
        });
      if (url.includes("/content?"))
        return response({
          event_id: "event-1",
          content: "expanded archived output",
          byte_length: 26,
          viewer_truncated: false,
          has_more: false,
        });
      if (url.endsWith("/attachments/blob"))
        return response({
          id: "blob",
          original_name: "output.txt",
          byte_length: 70031,
          available: true,
          content_type: "text/plain",
        });
      if (url.includes("content=true")) return new Response("POC_LARGE_END");
      throw new Error(`Unexpected request ${url}`);
    });
  });
  it("shows native session identity beside the agent in a full reader and keeps source inert", async () => {
    renderWithProviders(
      <TranscriptViewer location={location} onLocationChange={vi.fn()} />
    );
    expect(
      await screen.findByRole("button", {
        name: `Copy session ID: ${nativeId}`,
      })
    ).toBeInTheDocument();
    expect(await screen.findByText(/fixture total31/)).toHaveTextContent(
      "<script>not executable</script>"
    );
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByText(/truncated before capture/)).toBeInTheDocument();
    expect(screen.getByText(/8 active days/)).toBeInTheDocument();
    expect(api.apiFetch).not.toHaveBeenCalledWith(
      expect.stringContaining("/content?"),
      expect.anything()
    );
  });
  it("highlights the visible linked range and distinguishes attachment-backed truncation", async () => {
    const original = vi.mocked(api.apiFetch).getMockImplementation()!;
    vi.mocked(api.apiFetch).mockImplementation(async (...args) =>
      String(args[0]).includes("/events?")
        ? response({
            events: [
              event,
              { ...event, event_id: "middle" },
              { ...event, event_id: "last" },
            ],
            snapshot_revision: 4,
            status: "ok",
          })
        : original(...args)
    );
    renderWithProviders(
      <TranscriptViewer
        location={{ ...location, endEventId: "last" }}
        onLocationChange={vi.fn()}
      />
    );
    await screen.findAllByText(/fixture total31/);
    expect(document.querySelectorAll(".evidence-selected")).toHaveLength(3);
    expect(
      screen.getAllByText(/An archived attachment is available below/)
    ).toHaveLength(3);
  });
  it("loads expanded output and attachments only after explicit actions", async () => {
    renderWithProviders(
      <TranscriptViewer
        location={location}
        onLocationChange={vi.fn()}
        variant="drawer"
      />
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "Expand content" })
    );
    expect(
      await screen.findByText("expanded archived output")
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Preview attachment" }));
    expect(await screen.findByText("POC_LARGE_END")).toBeInTheDocument();
  });
  it("changes the source anchor for cross-month day jumps and native child sessions", async () => {
    const changed = vi.fn();
    renderWithProviders(
      <TranscriptViewer location={location} onLocationChange={changed} />
    );
    fireEvent.click(await screen.findByRole("button", { name: /2026-12-03/ }));
    expect(changed).toHaveBeenLastCalledWith(
      expect.objectContaining({ date: "2026-12-03", eventId: undefined })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "View child evidence" })
    );
    expect(changed).toHaveBeenLastCalledWith(
      expect.objectContaining({
        sessionId: "child",
        eventId: undefined,
        mode: "conversation",
      })
    );
  });
  it("passes stable before/after cursors and indexed revision instead of fetching whole sessions", async () => {
    renderWithProviders(
      <TranscriptViewer location={location} onLocationChange={vi.fn()} />
    );
    fireEvent.click(await screen.findByRole("button", { name: "Load later" }));
    await waitFor(() =>
      expect(api.apiFetch).toHaveBeenCalledWith(
        expect.stringContaining("after=newer"),
        expect.anything()
      )
    );
    const calls = vi
      .mocked(api.apiFetch)
      .mock.calls.map(([path]) => String(path));
    expect(calls.find((url) => url.includes("after=newer"))).toContain(
      "snapshot_revision=4"
    );
  });
  it("keeps legacy journal summaries available when originals do not exist", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue(response({ status: "absent" }));
    const open = vi.fn();
    renderWithProviders(
      <JournalEvidenceLink
        folderId="repo"
        entryId="legacy:entry"
        timezone="UTC"
        onOpen={open}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "View evidence" }));
    expect(
      await screen.findByText(
        "Original evidence is unavailable for this entry."
      )
    ).toBeInTheDocument();
    expect(open).not.toHaveBeenCalled();
  });
  it("shows an empty archived attachment without requesting an unsatisfiable byte range", async () => {
    const attachment = {
      id: "empty",
      original_name: "empty.txt",
      byte_length: 0,
      available: true,
      content_type: "text/plain",
    };
    vi.spyOn(api, "apiFetch").mockResolvedValue(response(attachment));
    renderWithProviders(
      <TranscriptAttachment attachment={attachment} location={location} />
    );
    fireEvent.click(screen.getByRole("button", { name: "Preview attachment" }));
    expect(
      await screen.findByText("Empty attachment (0 bytes).")
    ).toBeInTheDocument();
    expect(api.apiFetch).toHaveBeenCalledTimes(1);
    expect(
      screen.getByRole("button", { name: "Download attachment" })
    ).toBeInTheDocument();
  });
  it("shows a feature-unavailable message without hiding the selected source", async () => {
    vi.spyOn(api, "apiFetch").mockRejectedValue(
      new ApiError({ status: 404, userMessage: "Not found" })
    );
    renderWithProviders(
      <TranscriptViewer location={location} onLocationChange={vi.fn()} />
    );
    expect(
      await screen.findByText(/archival is not enabled yet/)
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });
});
