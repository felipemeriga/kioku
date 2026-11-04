import { describe, expect, it, vi } from "vitest";
import { runChatTransport } from "./chatTransport";

const event = (data: object) => `data: ${JSON.stringify(data)}\n\n`;
const response = (data: string) => new Response(data, { status: 200 });
const headers = async () => ({ Authorization: "Bearer fixture" });
const pause = async () => undefined;

describe("durable native chat transport", () => {
  it("reconnects after last processed event and deduplicates deltas before canonical replacement", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        response(
          event({ job_id: "job", turn_id: "turn" }) +
            event({ event_id: 1, token: "partial" }),
        ),
      )
      .mockResolvedValueOnce(
        response(
          event({ job_id: "job", event_id: 1, token: "partial" }) +
            event({ event_id: 2, replace: "canonical answer", done: true }),
        ),
      );
    const frames: Record<string, unknown>[] = [];
    await runChatTransport({
      payload: { turn_id: "turn" },
      headers,
      pause,
      fetcher,
      onFrame: (frame) => frames.push(frame),
    });
    expect(fetcher.mock.calls[1][0]).toBe("/api/chat/jobs/job/events?after=1");
    expect(frames.filter((frame) => frame.token)).toHaveLength(1);
    expect(frames.at(-1)?.replace).toBe("canonical answer");
  });

  it("recovers a POST response lost after durable acceptance without another POST", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockRejectedValueOnce(new TypeError("lost"))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ job_id: "job", state: "submitted" })),
      )
      .mockResolvedValueOnce(
        response(
          event({ job_id: "job", event_id: 1, replace: "saved", done: true }),
        ),
      );
    await runChatTransport({
      payload: { turn_id: "stable" },
      headers,
      pause,
      fetcher,
      onFrame: vi.fn(),
    });
    expect(fetcher.mock.calls[1][0]).toBe("/api/chat/turns/stable");
    expect(
      fetcher.mock.calls.filter((call) => call[1]?.method === "POST"),
    ).toHaveLength(1);
  });

  it("never resubmits an unknown legacy request after a lost POST", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockRejectedValueOnce(new TypeError("lost"))
      .mockImplementation(async () => new Response("", { status: 404 }));
    await expect(
      runChatTransport({
        payload: { turn_id: "stable" },
        headers,
        pause,
        fetcher,
        onFrame: vi.fn(),
      }),
    ).rejects.toThrow("Reload the conversation");
    expect(
      fetcher.mock.calls.filter((call) => call[1]?.method === "POST"),
    ).toHaveLength(1);
  });

  it("rejects a terminal error and does not treat it as done", async () => {
    const done = vi.fn();
    await expect(
      runChatTransport({
        payload: { turn_id: "stable" },
        headers,
        pause,
        fetcher: vi
          .fn<typeof fetch>()
          .mockResolvedValue(
            response(event({ error: "job.uncertain", done: true })),
          ),
        onFrame: done,
      }),
    ).rejects.toThrow("job.uncertain");
    expect(done).not.toHaveBeenCalled();
  });
});

it("preserves a typed pre-job policy conflict without attempting inference again", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
    response(
      event({
        error: "conversation_policy_changed: rebuild required",
        error_code: "conversation_policy_changed",
        recovery_required: true,
        turn_id: "stable",
      }),
    ),
  );
  await expect(
    runChatTransport({
      payload: { turn_id: "stable" },
      headers,
      pause,
      fetcher,
      onFrame: vi.fn(),
    }),
  ).rejects.toMatchObject({ status: 409, code: "conversation_policy_changed" });
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("replays a mounted accepted execution with GET only and canonical replacement", async () => {
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "turn",
          job_id: "job",
          conversation_id: "conversation",
          state: "submitted",
        }),
      ),
    )
    .mockResolvedValueOnce(
      response(
        event({ job_id: "job", event_id: 1, token: "partial" }) +
          event({ event_id: 2, replace: "canonical", done: true }),
      ),
    );
  const frames = vi.fn();
  await runChatTransport({
    payload: {},
    resume: { turn_id: "turn", job_id: "job", conversation_id: "conversation" },
    headers,
    fetcher,
    pause,
    onFrame: frames,
  });
  expect(fetcher.mock.calls.map((call) => call[0])).toEqual([
    "/api/chat/turns/turn",
    "/api/chat/jobs/job/events?after=0",
  ]);
  expect(
    fetcher.mock.calls.every(
      (call) => call[1]?.method !== "POST" && !call[1]?.body,
    ),
  ).toBe(true);
  expect(frames.mock.calls.at(-1)?.[0].replace).toBe("canonical");
});

it.each([403, 404])(
  "never posts or resumes an inaccessible saved reference (%s)",
  async (status) => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValue(new Response("{}", { status }));
    await expect(
      runChatTransport({
        payload: {},
        resume: {
          turn_id: "turn",
          job_id: "job",
          conversation_id: "conversation",
        },
        headers,
        fetcher,
        pause,
        onFrame: vi.fn(),
      }),
    ).rejects.toThrow("Could not recover");
    expect(fetcher).toHaveBeenCalledTimes(1);
  },
);

it("rejects a stale or foreign conversation mapping without following its job", async () => {
  const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
    new Response(
      JSON.stringify({
        id: "turn",
        job_id: "other",
        conversation_id: "foreign",
      }),
    ),
  );
  await expect(
    runChatTransport({
      payload: {},
      resume: {
        turn_id: "turn",
        job_id: "job",
        conversation_id: "conversation",
      },
      headers,
      fetcher,
      pause,
      onFrame: vi.fn(),
    }),
  ).rejects.toThrow("identity changed");
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("aborts a remounted listener without retrying or cancelling server execution", async () => {
  const controller = new AbortController();
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "turn",
          job_id: "job",
          conversation_id: "conversation",
        }),
      ),
    )
    .mockImplementationOnce(async () => {
      controller.abort();
      throw new DOMException("Aborted", "AbortError");
    });
  await expect(
    runChatTransport({
      payload: {},
      resume: {
        turn_id: "turn",
        job_id: "job",
        conversation_id: "conversation",
      },
      signal: controller.signal,
      headers,
      fetcher,
      pause,
      onFrame: vi.fn(),
    }),
  ).rejects.toThrow("Aborted");
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(fetcher.mock.calls[1][1]?.signal).toBe(controller.signal);
});

it("reports a saved terminal quota failure without reposting or an event replay loop", async () => {
  const fetcher = vi
    .fn<typeof fetch>()
    .mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "turn",
          job_id: "job",
          conversation_id: "conversation",
          state: "failed",
          error_code: "quota_limited",
        }),
      ),
    );
  await expect(
    runChatTransport({
      payload: {},
      resume: {
        turn_id: "turn",
        job_id: "job",
        conversation_id: "conversation",
      },
      headers,
      fetcher,
      pause,
      onFrame: vi.fn(),
    }),
  ).rejects.toMatchObject({ code: "quota_limited", status: 409 });
  expect(fetcher).toHaveBeenCalledTimes(1);
});
