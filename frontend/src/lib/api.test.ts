import { describe, it, expect, vi, beforeEach } from "vitest";
import * as api from "./api";

vi.mock("./supabase", () => ({
  supabase: {
    auth: {
      getSession: async () => ({ data: { session: { access_token: "t" } } }),
    },
  },
}));

describe("getFolderStatus", () => {
  beforeEach(() => vi.restoreAllMocks());
  it("GETs the status endpoint", async () => {
    const payload = { graph_at: "x", architecture_at: "y" };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(payload), { status: 200 })),
    );
    const out = await api.getFolderStatus("f1");
    expect(out.architecture_at).toBe("y");
    expect(
      (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][0],
    ).toBe("/api/folders/f1/status");
  });
});

it("applies native canonical replacement and debug before done", async () => {
  const sequence: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          'data: {"job_id":"job","event_id":1,"token":"provisional"}\n\n' +
            'data: {"event_id":2,"replace":"canonical","debug":{"reasoning":[],"tool_calls":[],"retrieval":[]},"done":true}\n\n',
        ),
    ),
  );
  await api.streamChat(
    "conversation",
    "question",
    () => sequence.push("token"),
    () => sequence.push("done"),
    undefined,
    undefined,
    "haiku",
    "agentic",
    true,
    () => sequence.push("debug"),
    undefined,
    undefined,
    () => sequence.push("replace"),
  );
  expect(sequence).toEqual(["token", "debug", "replace", "done"]);
  const body = JSON.parse(
    (fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock
      .calls[0][1].body as string,
  );
  expect(body.turn_id).toMatch(/^[0-9a-f-]{36}$/);
});
