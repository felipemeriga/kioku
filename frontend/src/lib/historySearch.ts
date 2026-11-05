export type HistoryFilters = {
  q: string;
  mode: "words" | "phrase" | "regex";
  fields: "all" | "title";
  agent: string;
  session_id: string;
  date_from: string;
  date_to: string;
};
export const emptyHistoryFilters: HistoryFilters = {
  q: "",
  mode: "words",
  fields: "all",
  agent: "",
  session_id: "",
  date_from: "",
  date_to: "",
};
export const hasHistoryFilters = (f: HistoryFilters) =>
  !!(f.q.trim() || f.agent || f.session_id || f.date_from || f.date_to);
export type HistorySearchSession = {
  agent: string;
  session_id: string;
  title: string;
  summary?: string;
  dates: string[];
  entry_count: number;
  title_match: boolean;
  overview_match: boolean;
  matches: { id: string; date: string; excerpt: string }[];
};
export type HistorySearchResponse = {
  sessions: HistorySearchSession[];
  total_sessions: number;
  total_entries: number;
  has_more: boolean;
  coverage?: { pending_days?: number };
};

export function validateHistoryFilters(
  filters: HistoryFilters
): Partial<Record<keyof HistoryFilters, string>> {
  const errors: Partial<Record<keyof HistoryFilters, string>> = {};
  if (
    typeof filters.q !== "string" ||
    filters.q.length > 160 ||
    Array.from(filters.q).some(
      (char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127
    )
  )
    errors.q = "Use up to 160 characters without control characters.";
  if (!["words", "phrase", "regex"].includes(filters.mode))
    errors.mode = "Choose all words, exact phrase, or regex.";
  if (!["all", "title"].includes(filters.fields))
    errors.fields = "Choose all journal content or titles only.";
  if (!["", "codex", "claude_code"].includes(filters.agent))
    errors.agent = "Choose Codex, Claude Code, or all agents.";
  if (
    filters.session_id &&
    (!/^[A-Za-z0-9._:-]+$/.test(filters.session_id) ||
      filters.session_id.length > 256)
  )
    errors.session_id =
      "Use up to 256 letters, numbers, dots, underscores, colons or hyphens.";
  for (const key of ["date_from", "date_to"] as const) {
    const value = filters[key];
    if (value) {
      const instant = new Date(`${value}T00:00:00Z`);
      if (
        !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
        !Number.isFinite(instant.getTime()) ||
        instant.toISOString().slice(0, 10) !== value
      )
        errors[key] = "Enter a valid date in YYYY-MM-DD format.";
    }
  }
  if (
    !errors.date_from &&
    !errors.date_to &&
    filters.date_from &&
    filters.date_to &&
    filters.date_from > filters.date_to
  )
    errors.date_to = "The end date must be on or after the start date.";
  if (
    filters.mode === "regex" &&
    filters.q &&
    (/[(){}]/.test(filters.q) || /\\[1-9]|[+*?][+*?]/.test(filters.q))
  )
    errors.q =
      "Regex supports classes, anchors, alternatives and simple repetition. Groups and backreferences are unavailable.";
  return errors;
}
