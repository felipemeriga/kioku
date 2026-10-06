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
      vi.fn(async () => new Response(JSON.stringify(payload), { status: 200 }))
    );
    const out = await api.getFolderStatus("f1");
    expect(out.architecture_at).toBe("y");
    expect(
      (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][0]
    ).toBe("/api/folders/f1/status");
  });
});
