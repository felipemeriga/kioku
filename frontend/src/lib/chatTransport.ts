/** Durable native replay without ever repeating an unknown legacy API request. */
export class ChatTransportError extends Error {
  status: number;
  constructor(message: string, status = 0) {
    super(message);
    this.status = status;
  }
}

export type ChatFrame = Record<string, unknown>;

export async function runChatTransport(options: {
  payload: Record<string, unknown>;
  headers: () => Promise<Record<string, string>>;
  onFrame: (frame: ChatFrame) => void;
  fetcher?: typeof fetch;
  pause?: (ms: number) => Promise<void>;
}): Promise<void> {
  const fetcher = options.fetcher ?? fetch;
  const pause =
    options.pause ??
    ((ms) => new Promise((resolve) => setTimeout(resolve, ms)));
  let jobId: string | undefined;
  let cursor = 0;
  let first = true;
  const turnId = options.payload.turn_id;
  let knownNative = false;

  async function recover(): Promise<void> {
    if (jobId) return;
    for (let attempt = 0; attempt < 5; attempt++) {
      const response = await fetcher(`/api/chat/turns/${turnId}`, {
        headers: await options.headers(),
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
          throw new ChatTransportError(
            turn.error_code ?? `Execution ${turn.state}`,
            409,
          );
        }
        // A durable prepared turn proves the exact same-key POST is safe.
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

  for (let retry = 0; retry < 4; retry++) {
    let response: Response;
    try {
      response = await fetcher(
        first ? "/api/chat" : `/api/chat/jobs/${jobId}/events?after=${cursor}`,
        {
          method: first ? "POST" : "GET",
          headers: await options.headers(),
          ...(first ? { body: JSON.stringify(options.payload) } : {}),
        },
      );
      first = false;
      if (!response.ok) {
        let detail = "Chat request failed";
        try {
          const body = await response.json();
          detail =
            typeof body.detail === "string"
              ? body.detail
              : JSON.stringify(body.detail ?? body);
        } catch {
          /* Preserve HTTP status for non-JSON proxy errors. */
        }
        throw new ChatTransportError(detail, response.status);
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
              throw new ChatTransportError(
                typeof frame.error === "string"
                  ? frame.error
                  : JSON.stringify(frame.error),
                500,
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
