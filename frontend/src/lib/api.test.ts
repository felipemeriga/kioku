import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import * as api from "./api";
import { supabase } from "./supabase";

vi.mock("./supabase", () => ({
  supabase: {
    auth: {
      getSession: vi.fn(async () => ({
        data: { session: { access_token: "t" } },
      })),
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

describe("API error messages", () => {
  it.each([
    [502, "text/html", "<html><body>proxy secret=hidden</body></html>"],
    [503, "text/plain", "Traceback: password=hidden"],
    [500, "application/json", '{"detail":"secret=hidden"}'],
  ])("does not expose a %s diagnostic body", async (status, type, body) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(body, {
            status,
            headers: { "content-type": type },
          }),
      ),
    );
    const error = await api.apiFetch("/api/documents").catch((err) => err);
    expect(error).toBeInstanceOf(api.ApiError);
    expect(error.status).toBe(status);
    expect(error.userMessage).toMatch(/server.*try again/i);
    expect(error.userMessage).not.toMatch(/<html>|hidden|Traceback/);
    expect(error.detail).toBeUndefined();
  });

  it("preserves useful FastAPI validation messages without echoing input", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              detail: [
                {
                  loc: ["body", "filename"],
                  msg: "Field required",
                  input: "hidden",
                },
              ],
            }),
            { status: 422, headers: { "content-type": "application/json" } },
          ),
      ),
    );
    await expect(api.apiFetch("/api/documents")).rejects.toMatchObject({
      status: 422,
      userMessage: "filename: Field required",
    });
  });

  it.each([
    [{ detail: "Folder not found" }, "Folder not found"],
    [{ detail: "<html>secret=hidden</html>" }, "Not found."],
    [{ traceback: "secret=hidden" }, "Not found."],
  ])("only displays explicit safe client errors", async (body, expected) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify(body), {
            status: 404,
            headers: { "content-type": "application/json" },
          }),
      ),
    );
    await expect(api.apiFetch("/api/documents")).rejects.toMatchObject({
      status: 404,
      userMessage: expected,
    });
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

it("exposes typed native rebuild recovery for a pre-job SSE policy conflict", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          'data: {"error":"rebuild required","error_code":"conversation_policy_changed","recovery_required":true,"turn_id":"stable"}\n\n',
        ),
    ),
  );
  let failure: unknown;
  try {
    await api.streamChat("conversation", "follow-up", vi.fn(), vi.fn());
  } catch (error) {
    failure = error;
  }
  expect(failure).toBeInstanceOf(api.ApiError);
  expect(api.requiresNativeRebuild(failure)).toBe(true);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it("preserves native recovery codes while exposing only a human API message", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            detail: {
              code: "conversation_needs_rebuild",
              diagnostic: "secret=hidden",
            },
          }),
          { status: 409, headers: { "content-type": "application/json" } },
        ),
    ),
  );
  const error = await api
    .streamChat("conversation", "question", vi.fn(), vi.fn())
    .catch((err) => err);
  expect(error).toBeInstanceOf(api.ApiError);
  expect(error.status).toBe(409);
  expect(error.detail).toEqual({ code: "conversation_needs_rebuild" });
  expect(api.requiresNativeRebuild(error)).toBe(true);
  expect(error.userMessage).toBe(
    "Rebuild this session from saved history to continue.",
  );
  expect(error.userMessage).not.toMatch(/hidden|diagnostic|[{}]/);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it.each(["cancelled", "execution_uncertain"])(
  "requires explicit rebuild for authoritative native %s",
  (code) => {
    expect(
      api.requiresNativeRebuild(
        new api.ApiError({
          status: 409,
          detail: { code },
          userMessage: "Native execution ended",
        }),
      ),
    ).toBe(true);
  },
);
it("does not infer a rebuild requirement from generic network or HTTP error text", () => {
  expect(api.requiresNativeRebuild(new Error("execution_uncertain"))).toBe(
    false,
  );
  expect(
    api.requiresNativeRebuild(
      new api.ApiError({ status: 0, userMessage: "cancelled connection" }),
    ),
  ).toBe(false);
  expect(
    api.requiresNativeRebuild(
      new api.ApiError({ status: 502, userMessage: "execution_uncertain" }),
    ),
  ).toBe(false);
});

describe("bounded conversation reads", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.mocked(supabase.auth.getSession).mockResolvedValue({
      data: { session: { access_token: "t" } },
    } as Awaited<ReturnType<typeof supabase.auth.getSession>>);
  });
  it.each(["authentication", "network", "body"])(
    "ends a stuck %s read with a retryable error",
    async (stage) => {
      vi.useFakeTimers();
      const pending = () => new Promise<never>(() => {});
      const fetchMock = vi.fn(
        stage === "network"
          ? pending
          : async () => ({ json: pending, ok: true }),
      );
      vi.stubGlobal("fetch", fetchMock);
      if (stage === "authentication")
        vi.mocked(supabase.auth.getSession).mockImplementation(pending);
      const read = api.fetchConversations();
      const rejected = expect(read).rejects.toMatchObject({
        status: 504,
        userMessage: expect.stringContaining("try again"),
      });
      await vi.advanceTimersByTimeAsync(api.CONVERSATION_READ_TIMEOUT_MS);
      await rejected;
      if (stage === "authentication") expect(fetchMock).not.toHaveBeenCalled();
      else
        expect(
          (fetchMock.mock.calls as unknown as [string, RequestInit][])[0][1]
            .signal?.aborted,
        ).toBe(true);
    },
  );
  it("cancels a selected conversation read immediately and allows the next read", async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<never>(() => {})),
    );
    const read = api.fetchConversation("old", controller.signal);
    controller.abort();
    await expect(read).rejects.toMatchObject({ name: "AbortError" });
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () => new Response(JSON.stringify({ id: "next", messages: [] })),
      ),
    );
    await expect(api.fetchConversation("next")).resolves.toMatchObject({
      id: "next",
    });
  });
});
