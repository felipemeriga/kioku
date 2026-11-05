const ignored = new Set(
  "the and for with from this that only field fields one payload event string option some none true false pub enum struct self return let fn type code".split(
    " ",
  ),
);
function terms(text: string): string[] {
  return text
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((word) => word.length > 2 && !ignored.has(word));
}

/** Select only an original contiguous source window; never reconstruct code. */
export function codeCitationPreview(value: string, claim = ""): string {
  const lines = value.replace(/\r\n/g, "\n").split("\n");
  const header =
    /^(?:\[(?:Code\s*:|(?:repo|file|lines?|symbol|source_type)(?:\s*[:=]\s*|\s+))[^\]]*\][ \t]*)+$/i;
  while (lines.length && (!lines[0].trim() || header.test(lines[0].trim())))
    lines.shift();
  if (lines.length)
    lines[0] = lines[0].replace(
      /^(?:\[(?:Code\s*:|(?:repo|file|lines?|symbol|source_type)(?:\s*[:=]\s*|\s+))[^\]]*\][ \t]?)+/i,
      "",
    );
  if (/^[ \t]*(?:`{3,}|~{3,})[\w+-]*[ \t]*$/.test(lines[0] ?? ""))
    lines.shift();
  if (/^[ \t]*(?:`{3,}|~{3,})[ \t]*$/.test(lines.at(-1) ?? "")) lines.pop();
  const wanted = new Set(terms(claim));
  const tokens = lines.map((line) => new Set(terms(line)));
  const frequency = new Map<string, number>();
  for (const words of tokens)
    for (const word of words)
      frequency.set(word, (frequency.get(word) ?? 0) + 1);
  let focus = 0,
    best = 0;
  tokens.forEach((words, index) => {
    const score = [...words].reduce(
      (sum, word) =>
        sum + (wanted.has(word) ? 1 / (frequency.get(word) ?? 1) : 0),
      0,
    );
    if (score > best) {
      focus = index;
      best = score;
    }
  });
  const start = best ? Math.max(0, focus - 2) : 0;
  const body = lines.slice(start, start + 20).join("\n");
  return (
    (start ? "…\n" : "") +
    body.slice(0, 2400) +
    (body.length > 2400 || lines.length > start + 20 ? "\n…" : "")
  );
}
