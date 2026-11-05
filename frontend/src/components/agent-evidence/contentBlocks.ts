import { detectedCodeSpans, syntax } from "./syntax";

export type ReadableKind = "markdown" | "code" | "terminal" | "json" | "text";

export interface ReadableBlock {
  kind: ReadableKind;
  text: string;
  language?: string;
}

const languages: Record<string, string> = {
  rs: "rust",
  rust: "rust",
  js: "javascript",
  jsx: "javascript",
  javascript: "javascript",
  ts: "typescript",
  tsx: "typescript",
  typescript: "typescript",
  py: "python",
  python: "python",
  go: "go",
  sh: "bash",
  shell: "bash",
  bash: "bash",
  zsh: "bash",
  json: "json",
  yml: "yaml",
  yaml: "yaml",
  sql: "sql",
  c: "c",
  h: "c",
  cpp: "cpp",
  hpp: "cpp",
  cc: "cpp",
  html: "xml",
  xml: "xml",
  svg: "xml",
  markup: "xml",
  css: "css",
  toml: "toml",
};

export function readableLanguage(value?: string): string | undefined {
  if (!value) return undefined;
  const lower = value.toLowerCase();
  return languages[lower] || (syntax.registered(lower) ? lower : undefined);
}

export function filePresentation(
  name: string,
  mime = ""
): { kind: ReadableKind; language?: string } {
  const extension = name.split(".").pop()?.toLowerCase();
  if (
    ["md", "markdown", "mdx"].includes(extension || "") ||
    mime.startsWith("text/markdown")
  )
    return { kind: "markdown" };
  if (
    extension === "json" ||
    /^application\/(?:[\w.+-]+\+)?json(?:;|$)/i.test(mime)
  )
    return { kind: "json", language: "json" };
  const language = readableLanguage(extension);
  if (language) return { kind: "code", language };
  return { kind: extension === "log" ? "terminal" : "text" };
}

export function previewableText(name: string, mime = ""): boolean {
  if (
    /^(text\/|application\/(?:json|x-ndjson|javascript|xml|[\w.+-]+\+json))/i.test(
      mime
    )
  )
    return true;
  // Unknown and source-code MIME hints are often application/octet-stream.
  const extension = name.split(".").pop()?.toLowerCase();
  return (
    !mime ||
    !!readableLanguage(extension) ||
    ["md", "markdown", "txt", "log", "csv", "jsonl", "ndjson"].includes(
      extension || ""
    )
  );
}

/** A bounded, conservative presentation hint. Native blocks and explicit fences win. */
export function readableBlocks(
  text: string,
  kind: ReadableKind = "markdown",
  complete = true,
  language?: string
): ReadableBlock[] {
  if (!complete)
    return [
      {
        kind: kind === "code" ? "code" : "text",
        text,
        ...(kind === "code" ? { language } : {}),
      },
    ];
  if (kind === "code" || (language && kind !== "json"))
    return [{ kind: "code", text, language }];
  if (kind === "text") return [{ kind, text }];
  if (
    text.length <= 65536 &&
    (kind === "json" ||
      text.trimStart().startsWith("{") ||
      text.trimStart().startsWith("["))
  ) {
    try {
      const parsed: unknown = JSON.parse(text);
      if (kind === "json" || (parsed !== null && typeof parsed === "object"))
        return [
          {
            kind: "json",
            text: JSON.stringify(parsed, null, 2),
            language: "json",
          },
        ];
    } catch {
      /* Incomplete or non-JSON text remains faithful text below. */
    }
  }
  if (kind === "json") return [{ kind: "text", text }];
  if (kind === "markdown" && /(^|\n)\s*(?:```|~~~)/.test(text))
    return [{ kind, text }];
  if (text.length > 65536) return [{ kind, text }];
  const spans = detectedCodeSpans(text);
  if (!spans.length) return [{ kind, text }];
  const result: ReadableBlock[] = [];
  let cursor = 0;
  for (const span of spans) {
    if (span.start > cursor)
      result.push({ kind, text: text.slice(cursor, span.start) });
    result.push({
      kind: "code",
      text: text.slice(span.start, span.end),
      language: span.language,
    });
    cursor = span.end;
  }
  if (cursor < text.length) result.push({ kind, text: text.slice(cursor) });
  return result;
}
