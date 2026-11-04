/** Durable native replay without ever repeating an unknown legacy API request. */
export class ChatTransportError extends Error {
  status: number;
  code?: string;
  constructor(message: string, status = 0, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export type ChatFrame = Record<string, unknown>;

const nativeMessages: Record<string, string> = {
  cancelled: "Response cancelled.",
  quota_limited:
    "The native provider's usage limit was reached. Please try again later.",
  reauth_required:
    "The native provider needs to be signed in again. Please contact an administrator.",
  wall_timeout: "The response took too long and was stopped. Please try again.",
  conversation_policy_changed:
    "The model or mode changed. Rebuild this session from saved history to continue.",
  conversation_needs_rebuild:
    "Rebuild this session from saved history to continue.",
  execution_uncertain:
    "The response could not be confirmed. Check the saved conversation before continuing.",
  unverified_citation:
    "The response's sources could not be verified. Please try again.",
  tool_backend_unavailable:
    "Knowledge tools are temporarily unavailable. Please try again.",
  invalid_tool_backend:
    "Knowledge tools could not be connected. Please try again.",
  prelaunch_failed: "The response could not be started. Please try again.",
};

function chatFailure(error: unknown, status: number, explicitCode?: unknown) {
  const nestedCode =
    error && typeof error === "object" && "code" in error
      ? error.code
      : undefined;
  const code =
    typeof explicitCode === "string"
      ? explicitCode
      : typeof nestedCode === "string"
        ? nestedCode
        : typeof error === "string" && Object.hasOwn(nativeMessages, error)
          ? error
          : undefined;
  let message =
    code && Object.hasOwn(nativeMessages, code)
      ? nativeMessages[code]
      : "Chat request failed. Please try again.";
  // Legacy API errors can be useful plain text; never expose serialized native
  // objects, proxy HTML, stack traces or diagnostic credential assignments.
  if (
    !code &&
    typeof error === "string" &&
    error.trim() &&
    error.length <= 500 &&
    !/^\s*[[{]|<[^>]*>|Traceback|\bat \S+.*:\d+|(?:password|secret|authorization|api[_-]?key|access[_-]?token)\s*[:=]/i.test(
      error,
    )
  ) {
    message = error;
  }
  return new ChatTransportError(message, status, code);
}

function terminalFailure(turn: { error_code?: unknown; state?: string }) {
  const code =
    turn.error_code ??
    (turn.state === "cancelled"
      ? "cancelled"
      : turn.state === "uncertain"
        ? "execution_uncertain"
        : undefined);
  return chatFailure(undefined, 409, code);
}

export async function runChatTransport(options: {
  payload: Record<string, unknown>;
  headers: () => Promise<Record<string, string>>;
  onFrame: (frame: ChatFrame) => void;
  fetcher?: typeof fetch;
  pause?: (ms: number) => Promise<void>;
  resume?: { turn_id: string; job_id: string; conversation_id: string };
  signal?: AbortSignal;
}): Promise<void> {
  const fetcher = options.fetcher ?? fetch;
  const pause =
    options.pause ??
    ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  let jobId: string | undefined;
  let cursor = 0;
  let first = true;
  const turnId = options.resume?.turn_id ?? options.payload.turn_id;
  let knownNative = false;

  async function recover(): Promise<void> {
    if (jobId) return;
    for (let attempt = 0; attempt < 5; attempt++) {
      const response = await fetcher(`/api/chat/turns/${turnId}`, {
        headers: await options.headers(),
        signal: options.signal,
      });
      if (response.ok) {
        const turn = await response.json();
        knownNative = true;
        if (turn.job_id) {
          jobId = turn.job_id;
          first = false;
          return;
        }
        if (["failed", "cancelled", "uncertain"].includes(turn.state)) {
          throw terminalFailure(turn);
        }
        // A durable prepared turn proves the exact same-key POST is safe.
        if (options.resume)
          throw new ChatTransportError("Saved execution is not accepted", 409);
        first = true;
        return;
      }
      if (response.status !== 404)
        throw new ChatTransportError(
          "Could not recover chat execution",
          response.status,
        );
      await pause(250 * (attempt + 1));
    }
    throw new ChatTransportError(
      "Connection lost. Reload the conversation to check its saved answer.",
    );
  }

  if (options.resume) {
    const response = await fetcher(`/api/chat/turns/${turnId}`, {
      headers: await options.headers(),
      signal: options.signal,
    });
    if (!response.ok)
      throw new ChatTransportError(
        "Could not recover saved execution",
        response.status,
      );
    const turn = await response.json();
    if (
      turn.id !== turnId ||
      turn.conversation_id !== options.resume.conversation_id ||
      turn.job_id !== options.resume.job_id
    ) {
      throw new ChatTransportError("Saved execution identity changed", 409);
    }
    if (["failed", "cancelled", "uncertain"].includes(turn.state)) {
      throw terminalFailure(turn);
    }
    jobId = options.resume.job_id;
    knownNative = true;
    first = false;
  }
  for (let retry = 0; retry < 4; retry++) {
    let response: Response;
    try {
      response = await fetcher(
        first ? "/api/chat" : `/api/chat/jobs/${jobId}/events?after=${cursor}`,
        {
          method: first ? "POST" : "GET",
          signal: options.signal,
          headers: await options.headers(),
          ...(first ? { body: JSON.stringify(options.payload) } : {}),
        },
      );
      first = false;
      if (!response.ok) {
        let detail: unknown;
        let code: string | undefined;
        try {
          const body = await response.json();
          code =
            typeof body.detail?.code === "string"
              ? body.detail.code
              : typeof body.error?.code === "string"
                ? body.error.code
                : typeof body.error_code === "string"
                  ? body.error_code
                  : undefined;
          detail = body.detail ?? body.error;
        } catch {
          /* Preserve HTTP status for non-JSON proxy errors. */
        }
        throw chatFailure(detail, response.status, code);
      }
      const reader = response.body?.getReader();
      if (!reader) throw new ChatTransportError("Empty chat response");
      const decoder = new TextDecoder();
      let buffer = "";
      try {
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          buffer = buffer.replace(/\r\n/g, "\n");
          let boundary: number;
          while ((boundary = buffer.indexOf("\n\n")) >= 0) {
            const block = buffer.slice(0, boundary);
            buffer = buffer.slice(boundary + 2);
            const data = block
              .split("\n")
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).trimStart())
              .join("\n");
            if (!data) continue;
            let frame: ChatFrame;
            try {
              frame = JSON.parse(data);
            } catch {
              throw new ChatTransportError("Malformed chat event");
            }
            if (typeof frame.job_id === "string") {
              if (jobId && jobId !== frame.job_id)
                throw new ChatTransportError("Execution identity changed");
              jobId = frame.job_id;
              knownNative = true;
            }
            const sequence =
              typeof frame.event_id === "number" ? frame.event_id : undefined;
            if (sequence !== undefined && sequence <= cursor && !frame.done)
              continue;
            if (sequence !== undefined) cursor = Math.max(cursor, sequence);
            if (frame.error)
              throw chatFailure(
                frame.error,
                dataRecoveryStatus(frame),
                frame.error_code,
              );
            options.onFrame(frame);
            if (frame.done) return;
          }
        }
      } finally {
        await reader.cancel().catch(() => undefined);
        reader.releaseLock();
      }
      throw new ChatTransportError("Response ended before a terminal event");
    } catch (error) {
      if (options.signal?.aborted) throw error;
      if (error instanceof ChatTransportError && error.status > 0) throw error;
      if (retry === 3) throw error;
      await pause(250 * 2 ** retry);
      await recover();
      if (!knownNative) throw error;
      options.onFrame({
        stage: "thinking",
        detail: "Reconnecting to the saved execution…",
      });
    }
  }
}

function dataRecoveryStatus(frame: ChatFrame): number {
  return frame.recovery_required ? 409 : 500;
}
