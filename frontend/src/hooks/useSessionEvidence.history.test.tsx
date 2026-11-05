import { beforeEach, describe, expect, it, vi } from "vitest";
import { waitFor } from "@testing-library/react";
import { renderWithProviders } from "../test/renderWithProviders";
import * as api from "../lib/api";
import { useSessionEvidence } from "./useSessionEvidence";
import type { EvidenceLocation } from "../lib/agentEvidenceApi";
vi.mock("../lib/supabase", () => ({
  supabase: { auth: { getSession: vi.fn() } },
}));
beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(api, "apiFetch").mockImplementation(
    async (path) =>
      new Response(
        JSON.stringify(
          String(path).includes("/days")
            ? { days: [], timezone: "UTC" }
            : String(path).includes("/events?")
            ? { events: [], snapshot_revision: 1, status: "ok" }
            : {
                id: "root",
                agent: "codex",
                native_session_id: "native",
                children: [],
                gaps: [],
              },
        ),
      ),
  );
});
function Harness({ location }: { location: EvidenceLocation }) {
  useSessionEvidence(location);
  return null;
}
describe("history source windows", () => {
  it("preserves a route date but requests only around when a first-event anchor exists", async () => {
    renderWithProviders(
      <Harness
        location={{
          folderId: "repo",
          sessionId: "child",
          date: "2026-11-04",
          eventId: "event-one",
          timezone: "America/Sao_Paulo",
          mode: "conversation",
        }}
      />,
    );
    await waitFor(() =>
      expect(
        vi
          .mocked(api.apiFetch)
          .mock.calls.some(([url]) => String(url).includes("/events?")),
      ).toBe(true),
    );
    const url = vi
      .mocked(api.apiFetch)
      .mock.calls.map(([url]) => String(url))
      .find((url) => url.includes("/events?"))!;
    expect(url).toContain("around=event-one");
    expect(url).not.toContain("date=");
    expect(url).toContain("timezone=America%2FSao_Paulo");
  });
  it("uses a local date window for direct routes without an anchor", async () => {
    renderWithProviders(
      <Harness
        location={{
          folderId: "repo",
          sessionId: "root",
          date: "2026-11-05",
          timezone: "UTC",
          mode: "conversation",
        }}
      />,
    );
    await waitFor(() =>
      expect(
        vi
          .mocked(api.apiFetch)
          .mock.calls.some(([url]) => String(url).includes("date=2026-11-05")),
      ).toBe(true),
    );
    expect(
      vi
        .mocked(api.apiFetch)
        .mock.calls.some(([url]) => String(url).includes("around=")),
    ).toBe(false);
  });
});
