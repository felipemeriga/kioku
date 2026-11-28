import { callRecallTool } from "../lib/recall-mcp.js";

export interface HistoryOptions {
  folder?: string;
  from?: string;
  through?: string;
  asOf?: string;
  timezone?: string;
  session?: string;
  evidenceMode?: string;
  order?: string;
  limit?: string;
  offset?: string;
}

export function integerOption(
  value: string | undefined,
  fallback: number,
  min: number,
  max: number
): number {
  if (value === undefined) return fallback;
  const n = Number(value);
  if (!/^\d+$/.test(value) || !Number.isSafeInteger(n) || n < min || n > max) {
    throw new Error(
      `Expected an integer between ${min} and ${max}, received '${value}'.`
    );
  }
  return n;
}

export function historyArguments(
  query: string,
  opts: HistoryOptions
): Record<string, unknown> {
  const timezone =
    opts.timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone;
  new Intl.DateTimeFormat("en", { timeZone: timezone });
  for (const day of [opts.from, opts.through]) {
    if (
      day &&
      (!/^\d{4}-\d{2}-\d{2}$/.test(day) ||
        !Number.isFinite(Date.parse(day)) ||
        new Date(day).toISOString().slice(0, 10) !== day)
    ) {
      throw new Error("Dates must be valid YYYY-MM-DD calendar dates.");
    }
  }
  if (opts.from && opts.through && opts.from > opts.through)
    throw new Error("--from must not be after --through.");
  const order = opts.order ?? "chronological";
  if (!["chronological", "latest", "relevance"].includes(order))
    throw new Error("Order must be chronological, latest or relevance.");
  const evidenceMode = opts.evidenceMode;
  if (
    evidenceMode !== undefined &&
    !["hydrate", "cached-preview"].includes(evidenceMode)
  ) {
    throw new Error("Evidence mode must be hydrate or cached-preview.");
  }
  return Object.fromEntries(
    Object.entries({
      query,
      folder: opts.folder,
      from_date: opts.from,
      through_date: opts.through,
      as_of: opts.asOf,
      timezone,
      session: opts.session,
      evidence_mode:
        evidenceMode === "cached-preview" ? "cached_preview" : evidenceMode,
      order,
      limit: integerOption(opts.limit, 10, 1, 50),
      offset: integerOption(opts.offset, 0, 0, 1000000),
    }).filter(([, value]) => value !== undefined)
  );
}

export async function history(
  query: string,
  opts: HistoryOptions
): Promise<void> {
  console.log(
    JSON.stringify(
      await callRecallTool(
        "search_agent_history",
        historyArguments(query, opts)
      ),
      null,
      2
    )
  );
}

export async function evidence(
  reference: string,
  opts: { before?: string; after?: string; chars?: string }
): Promise<void> {
  console.log(
    JSON.stringify(
      await callRecallTool("read_agent_evidence", {
        reference,
        before_records: integerOption(opts.before, 1, 0, 3),
        after_records: integerOption(opts.after, 1, 0, 3),
        char_limit: integerOption(opts.chars, 8000, 1000, 16000),
      }),
      null,
      2
    )
  );
}

export async function codeSearch(
  query: string,
  opts: { folder?: string; language?: string; limit?: string }
): Promise<void> {
  console.log(
    JSON.stringify(
      await callRecallTool("code_search", {
        query,
        ...(opts.folder ? { folder: opts.folder } : {}),
        ...(opts.language ? { language: opts.language } : {}),
        top_k: integerOption(opts.limit, 8, 1, 30),
      }),
      null,
      2
    )
  );
}
