import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "../../test/renderWithProviders";
import * as api from "../../lib/api";
import * as evidenceApi from "../../lib/agentEvidenceApi";
import type {
  EvidenceEvent,
  EvidenceLocation,
} from "../../lib/agentEvidenceApi";
import TranscriptEvent, { RawTranscriptRecord } from "./TranscriptEvent";
import TranscriptAttachment from "./TranscriptAttachment";
vi.mock("../../lib/supabase", () => ({
  supabase: { auth: { getSession: vi.fn() } },
}));
const location: EvidenceLocation = {
  folderId: "repo",
  sessionId: "session",
  timezone: "UTC",
  mode: "conversation",
};
const event: EvidenceEvent = {
  event_id: "event",
  role: "tool",
  event_type: "tool_result",
  event_at: "2026-11-04T10:00:00Z",
  content_preview: '{"native":"wrapper"}',
  raw_available: true,
  viewer_truncated: false,
  source_truncated: false,
  attachments: [],
  source: {
    object_id: "object",
    stream_id: "parent",
    generation: 1,
    record_sequence: 1,
  },
};
beforeEach(() => {
  vi.restoreAllMocks();
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: vi.fn().mockResolvedValue(undefined) },
    configurable: true,
  });
});
describe("readable original evidence", () => {
  it("renders decoded blocks and distinct native execution metadata without success inference", () => {
    renderWithProviders(
      <TranscriptEvent
        event={{
          ...event,
          presentation: {
            version: 1,
            blocks: [
              {
                kind: "code",
                language: "rust",
                text: 'fn main() { println!("decoded"); }',
              },
              { kind: "terminal", text: "Observed output" },
            ],
            tool: {
              command_text: "cargo check",
              status: "completed",
              exit_code: 7,
              duration_seconds: 3.25,
              orchestration_seconds: 0.024,
            },
            viewer_truncated: false,
            source_truncated: false,
          },
        }}
        location={location}
        selected={false}
        onChild={vi.fn()}
      />,
    );
    expect(document.querySelector("code")?.textContent).toBe("cargo check");
    expect(document.body).toHaveTextContent(
      'fn main() { println!("decoded"); }',
    );
    for (const text of [
      "Completed",
      "Exit 7",
      "Command 3.25 s",
      "Orchestration 0.024 s",
    ])
      expect(screen.getByText(text)).toBeInTheDocument();
    expect(screen.queryByText(/Success/)).toBeNull();
    expect(document.body).not.toHaveTextContent('"native":"wrapper"');
  });
  it("formats complete native blocks independently of clipped legacy previews and trailing metadata", () => {
    renderWithProviders(
      <TranscriptEvent
        event={{
          ...event,
          viewer_truncated: true,
          presentation: {
            version: 1,
            blocks: [
              {
                kind: "json",
                text: '{"complete":true}',
                viewer_truncated: false,
              },
              { kind: "json", text: '{"clipped":', viewer_truncated: true },
            ],
            viewer_truncated: true,
            source_truncated: false,
          },
        }}
        location={location}
        selected={false}
        onChild={vi.fn()}
      />,
    );
    expect(document.body).toHaveTextContent('"complete": true');
    expect(document.body).toHaveTextContent('{"clipped":');
  });
  it("does not duplicate an exact command block and labels copies as archived previews", () => {
    const download = vi
      .spyOn(evidenceApi, "downloadEvidence")
      .mockResolvedValue(undefined);
    renderWithProviders(
      <TranscriptEvent
        event={{
          ...event,
          presentation: {
            version: 1,
            blocks: [{ kind: "code", language: "bash", text: "echo safe" }],
            tool: { command_text: "echo safe" },
            viewer_truncated: false,
            source_truncated: false,
          },
        }}
        location={location}
        selected={false}
        onChild={vi.fn()}
      />,
    );
    expect(document.querySelectorAll("pre code")).toHaveLength(1);
    fireEvent.click(
      screen.getByRole("button", { name: "Copy archived preview" }),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
      event.content_preview,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Download original record" }),
    );
    expect(download).toHaveBeenCalledWith(location, "raw", "event");
  });
  it("formats only complete JSON while Source and copy preserve original characters and LF", () => {
    const raw = '{"payload":{"text":"line1\\nline2"}}\n';
    renderWithProviders(
      <RawTranscriptRecord
        record={{
          event_id: "raw",
          source: event.source,
          byte_length: new TextEncoder().encode(raw).byteLength,
          sha256: "fixture",
          raw_text: raw,
          raw_encoding: "utf-8",
          viewer_truncated: false,
        }}
        location={location}
      />,
    );
    expect(screen.getByRole("button", { name: "Formatted" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(document.querySelector("pre code")?.textContent).toContain(
      '"payload": {',
    );
    fireEvent.click(screen.getByRole("button", { name: "Source" }));
    expect(document.querySelector(".evidence-pre")?.textContent).toBe(raw);
    fireEvent.click(screen.getByRole("button", { name: "Copy source record" }));
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(raw);
  });
  it("keeps large numeric lexemes, decimal spelling and duplicate keys in formatted source", () => {
    const raw =
      '{"id":9223372036854775807,"dup":1,"dup":2,"amount":1.2300,"text":"\\u0061"}\n';
    renderWithProviders(
      <RawTranscriptRecord
        record={{
          event_id: "raw",
          source: event.source,
          byte_length: new TextEncoder().encode(raw).byteLength,
          sha256: "fixture",
          raw_text: raw,
          raw_encoding: "utf-8",
          viewer_truncated: false,
        }}
        location={location}
      />,
    );
    const formatted = document.querySelector("pre code")?.textContent ?? "";
    expect(formatted).toContain("9223372036854775807");
    expect(formatted).toContain("1.2300");
    expect(formatted.match(/"dup"/g)).toHaveLength(2);
    expect(formatted).toContain("\\u0061");
    fireEvent.click(screen.getByRole("button", { name: "Source" }));
    expect(document.querySelector(".evidence-pre")?.textContent).toBe(raw);
  });
  it("does not prettify a bounded source record even when the prefix is valid JSON", () => {
    renderWithProviders(
      <RawTranscriptRecord
        record={{
          event_id: "raw",
          source: event.source,
          byte_length: 9000,
          sha256: "fixture",
          raw_text: '{"prefix":true}',
          raw_encoding: "utf-8",
          viewer_truncated: true,
        }}
        location={location}
      />,
    );
    expect(screen.queryByRole("button", { name: "Formatted" })).toBeNull();
    expect(document.querySelector(".evidence-pre")?.textContent).toBe(
      '{"prefix":true}',
    );
    expect(
      screen.getByRole("button", { name: "Copy source preview" }),
    ).toBeInTheDocument();
  });
  it("keeps offset fragments faithful instead of interpreting standalone JSON", async () => {
    vi.spyOn(api, "apiFetch").mockImplementation(
      async (path) =>
        new Response(
          JSON.stringify(
            String(path).includes("offset=12")
              ? {
                  event_id: "event",
                  content: '{"tail":true}',
                  byte_length: 25,
                  viewer_truncated: false,
                  has_more: false,
                }
              : {
                  event_id: "event",
                  content: '{"first":[',
                  byte_length: 25,
                  viewer_truncated: true,
                  has_more: true,
                  next_offset: 12,
                },
          ),
        ),
    );
    renderWithProviders(
      <TranscriptEvent
        event={{ ...event, viewer_truncated: true }}
        location={location}
        selected={false}
        onChild={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Expand content" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Next content portion" }),
    );
    await screen.findByText('{"tail":true}');
    expect(document.body).not.toHaveTextContent('"tail": true');
    expect(
      screen.getByRole("button", { name: "Back to beginning" }),
    ).toBeInTheDocument();
  });
  it("lazily renders source attachments using filename language", async () => {
    const text = 'fn reconnect() { println!("safe"); }';
    const mock = vi.spyOn(api, "apiFetch").mockImplementation(async (path) =>
      String(path).includes("content=true")
        ? new Response(text)
        : new Response(
            JSON.stringify({
              id: "file",
              original_name: "worker.rs",
              content_type: "application/octet-stream",
              byte_length: new TextEncoder().encode(text).byteLength,
              available: true,
            }),
          ),
    );
    renderWithProviders(
      <TranscriptAttachment
        attachment={{
          id: "file",
          original_name: "worker.rs",
          byte_length: text.length,
          available: true,
          content_type: "application/octet-stream",
        }}
        location={location}
      />,
    );
    expect(mock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Preview attachment" }));
    await waitFor(() =>
      expect(document.querySelector("pre code")?.textContent).toBe(text),
    );
    expect(screen.getByText("rust")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Download attachment" }),
    ).toBeInTheDocument();
  });
  it("keeps binary attachments download-only and inert", async () => {
    const mock = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "image",
          original_name: "image.png",
          content_type: "image/png",
          byte_length: 10,
          available: true,
        }),
      ),
    );
    renderWithProviders(
      <TranscriptAttachment
        attachment={{
          id: "image",
          original_name: "image.png",
          content_type: "image/png",
          byte_length: 10,
          available: true,
        }}
        location={location}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Preview attachment" }));
    await screen.findByText(
      "Binary attachment. Download to inspect its original bytes.",
    );
    expect(
      mock.mock.calls.some(([url]) => String(url).includes("content=true")),
    ).toBe(false);
    expect(document.querySelector("img,iframe,script")).toBeNull();
  });
});
