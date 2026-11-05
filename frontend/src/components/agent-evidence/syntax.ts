import { common, createLowlight } from "lowlight";

/** One mature grammar registry for explicit highlighting and conservative detection. */
export const syntax = createLowlight(common);
type SyntaxNode = ReturnType<typeof syntax.highlight>["children"][number];
const AUTO_LANGUAGES = ["rust", "javascript", "python", "go", "cpp", "bash"];

export function detectedCodeSpans(
  text: string
): Array<{ start: number; end: number; language: string }> {
  if (text.length < 40 || text.length > 16384) return [];
  const lines = text.match(/[^\n]*(?:\n|$)/g)?.filter(Boolean) ?? [];
  if (lines.length < 2 || lines.length > 512) return [];
  const tree = syntax.highlightAuto(text, { subset: AUTO_LANGUAGES });
  const language = tree.data?.language;
  if (!language || (tree.data?.relevance ?? 0) < 4) return [];
  const alternative = syntax.highlightAuto(text, {
    subset: AUTO_LANGUAGES.filter((value) => value !== language),
  });
  if ((tree.data?.relevance ?? 0) - (alternative.data?.relevance ?? 0) < 1)
    return [];

  const starts: number[] = [];
  let offset = 0;
  for (const line of lines) {
    starts.push(offset);
    offset += line.length;
  }
  function lineAt(position: number) {
    let low = 0,
      high = starts.length - 1;
    while (low < high) {
      const middle = Math.ceil((low + high) / 2);
      if (starts[middle] <= position) low = middle;
      else high = middle - 1;
    }
    return low;
  }
  const semanticLines = new Set<number>();
  offset = 0;
  function visit(node: SyntaxNode, semantic = false) {
    if (node.type === "text") {
      if (semantic && node.value.trim()) {
        const line = lineAt(offset),
          indent = lines[line].search(/\S/);
        // Start a block only where grammar-recognized syntax begins a line.
        if (indent >= 0 && offset - starts[line] <= indent)
          semanticLines.add(line);
      }
      offset += node.value.length;
    } else if (node.type === "element") {
      const classes = Array.isArray(node.properties.className)
        ? node.properties.className
        : [];
      const active =
        semantic ||
        classes.some((value) =>
          /^hljs-(?:keyword|built_in|title|type|meta)$/.test(String(value))
        );
      for (const child of node.children) visit(child as SyntaxNode, active);
    }
  }
  for (const child of tree.children) visit(child);
  const anchors = [...semanticLines].sort((a, b) => a - b);
  if (anchors.length < 2) return [];
  const continuation = (index: number) =>
    semanticLines.has(index) ||
    /^(?:\s|$|[()[\]{};,]+\s*$|\/\/|\/\*|\*|#)/.test(lines[index]);
  const groups: Array<{ first: number; last: number; anchors: number }> = [];
  for (const anchor of anchors) {
    const previous = groups.at(-1);
    if (
      previous &&
      lines
        .slice(previous.last + 1, anchor)
        .every((_, i) => continuation(previous.last + 1 + i))
    ) {
      previous.last = anchor;
      previous.anchors++;
    } else groups.push({ first: anchor, last: anchor, anchors: 1 });
  }
  return groups.flatMap((group) => {
    if (group.anchors < 2) return [];
    let end = group.last + 1;
    while (end < lines.length && continuation(end)) end++;
    const start = starts[group.first],
      finish = end < starts.length ? starts[end] : text.length;
    return finish - start >= 40 ? [{ start, end: finish, language }] : [];
  });
}
