import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "./api";
import {
  evidenceUrl,
  getAttachmentPreview,
  getEvidenceWindow,
  getJournalEvidence,
  type EvidenceLocation,
} from "./agentEvidenceApi";

vi.mock("./supabase", () => ({ supabase: { auth: { getSession: vi.fn() } } }));
const location: EvidenceLocation = {
  folderId: "repo",
  sessionId: "archive",
  mode: "conversation",
  timezone: "America/Sao_Paulo",
};
describe("agent evidence API contract", () => {
  beforeEach(() => vi.restoreAllMocks());
  it("encodes opaque journal IDs and propagates abort signals", async () => {
    const request = vi
      .spyOn(api, "apiFetch")
      .mockResolvedValue(new Response(JSON.stringify({ status: "absent" })));
    const signal = new AbortController().signal;
    await getJournalEvidence("repo/one", "codex:session/turn", signal);
    expect(request).toHaveBeenCalledWith(
      "/api/folders/repo%2Fone/agent-sessions/evidence-for-entry/codex%3Asession%2Fturn",
      { signal },
    );
  });
  it("treats accepted-but-indexing responses as processing rather than absent", async () => {
    vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response("{}", { status: 202 }),
    );
    const value = await getEvidenceWindow(location, {
      timezone: "UTC",
      around: "event/one",
    });
    expect(value.status).toBe("processing");
    expect(value.events).toEqual([]);
  });
  it("uses a raw window route with the same cursor and snapshot contract", async () => {
    const request = vi
      .spyOn(api, "apiFetch")
      .mockResolvedValue(new Response(JSON.stringify({ records: [] })));
    await getEvidenceWindow(
      { ...location, mode: "raw" },
      { timezone: "UTC", before: "cursor+opaque", snapshot_revision: 9 },
    );
    const url = String(request.mock.calls[0][0]);
    expect(url).toContain("/raw-records?");
    expect(url).toContain("before=cursor%2Bopaque");
    expect(url).toContain("snapshot_revision=9");
    expect(url).toContain("limit=50");
  });
  it("fetches attachment previews only as bounded authenticated ranges", async () => {
    const request = vi
      .spyOn(api, "apiFetch")
      .mockResolvedValue(new Response("source bytes"));
    expect(await getAttachmentPreview(location, "blob/id")).toBe(
      "source bytes",
    );
    expect(request).toHaveBeenCalledWith(
      "/api/folders/repo/agent-sessions/archive/attachments/blob%2Fid?content=true",
      { signal: undefined, headers: { Range: "bytes=0-65535" } },
    );
  });
  it("preserves source/range/mode/timezone in the canonical full-reader URL", () => {
    const url = evidenceUrl({
      ...location,
      eventId: "e/1",
      endEventId: "e/2",
      mode: "raw",
    });
    const params = new URL(url, "https://kioku.test").searchParams;
    expect(params.get("event")).toBe("e/1");
    expect(params.get("end")).toBe("e/2");
    expect(params.get("tz")).toBe("America/Sao_Paulo");
    expect(params.get("mode")).toBe("raw");
  });
});
