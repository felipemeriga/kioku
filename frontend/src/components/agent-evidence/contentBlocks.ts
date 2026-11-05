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
  html: "markup",
  xml: "markup",
  svg: "markup",
  markup: "markup",
  css: "css",
  toml: "toml",
};

export function readableLanguage(value?: string): string | undefined {
  return value ? languages[value.toLowerCase()] : undefined;
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
  if (!complete) return [{ kind: "text", text }];
  if (kind === "code" || (language && kind !== "json")) return [{ kind: "code", text, language }];
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
  const lines = text.match(/[^\n]*(?:\n|$)/g)?.filter(Boolean) ?? [];
  const start = lines.findIndex((line) =>
    /^use\s+[\w:]+(?:::|\{|;)/.test(line)
  );
  if (start < 0) return [{ kind, text }];
  const rustLine =
    /^(?:\s|$|use\s|(?:pub\s+)?(?:async\s+)?fn\s|impl(?:<|\s)|(?:struct|enum|trait|type|const|static|mod)\s|#\[|\/\/|[{}])/;
  let end = start + 1;
  while (end < lines.length && rustLine.test(lines[end])) end++;
  const code = lines.slice(start, end).join("");
  if (!/\bfn\s+\w+\s*\(/.test(code)) return [{ kind, text }];
  const structural = code.replace(
    /"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])'|\/\/[^\n]*/g,
    ""
  );
  let depth = 0;
  for (const character of structural) {
    if (character === "{") depth++;
    else if (character === "}" && --depth < 0) return [{ kind, text }];
  }
  if (depth !== 0 || !code.trimEnd().endsWith("}")) return [{ kind, text }];
  const result: ReadableBlock[] = [];
  if (start) result.push({ kind, text: lines.slice(0, start).join("") });
  result.push({ kind: "code", text: code, language: "rust" });
  if (end < lines.length)
    result.push({ kind, text: lines.slice(end).join("") });
  return result;
}
