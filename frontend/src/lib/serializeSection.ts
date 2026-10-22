export function serializeSection(content: unknown): string {
  if (content == null) return "";
  if (typeof content === "string") return content;
  if (Array.isArray(content))
    return content
      .map((v) => `- ${serializeSection(v).replace(/\n/g, "\n  ")}`)
      .join("\n");
  if (typeof content === "object") {
    return Object.keys(content as Record<string, unknown>)
      .sort()
      .map((k) => {
        const v = serializeSection((content as Record<string, unknown>)[k]);
        return v.includes("\n")
          ? `${k}:\n  ${v.replace(/\n/g, "\n  ")}`
          : `${k}: ${v}`;
      })
      .join("\n");
  }
  return String(content);
}
