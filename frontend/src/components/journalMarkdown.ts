type MarkdownNode = {
  type: string;
  value?: string;
  children?: MarkdownNode[];
};

const IDENTIFIER_RE =
  /(?:~?\/)?(?:[@\w.-]+\/)+[\w.-]+|\b[\w.-]+\.(?:tsx?|jsx?|py|rs|json|toml|ya?ml|md|sh|sql)\b|\b[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*\(\)/g;

/** Add inline-code styling to old journal prose without changing stored Markdown. */
export function decorateJournalMarkdown() {
  return (tree: MarkdownNode) => {
    function visit(node: MarkdownNode) {
      if (
        !node.children ||
        ["link", "image", "code", "inlineCode"].includes(node.type)
      )
        return;
      const children: MarkdownNode[] = [];
      for (const child of node.children) {
        if (child.type !== "text" || !child.value) {
          visit(child);
          children.push(child);
          continue;
        }
        let cursor = 0;
        for (const match of child.value.matchAll(IDENTIFIER_RE)) {
          const start = match.index;
          if (start > cursor)
            children.push({
              type: "text",
              value: child.value.slice(cursor, start),
            });
          children.push({ type: "inlineCode", value: match[0] });
          cursor = start + match[0].length;
        }
        if (cursor < child.value.length)
          children.push({ type: "text", value: child.value.slice(cursor) });
      }
      node.children = children;
    }
    visit(tree);
  };
}
