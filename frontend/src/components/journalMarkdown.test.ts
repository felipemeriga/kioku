import { expect, it } from "vitest";
import { decorateJournalMarkdown } from "./journalMarkdown";

it("decorates paths and functions in prose while leaving existing code intact", () => {
  const tree = {
    type: "root",
    children: [
      {
        type: "paragraph",
        children: [
          {
            type: "text",
            value:
              "The hook reads /home/felipe/.codex/config.toml via parseTurn().",
          },
          { type: "inlineCode", value: "alreadyStyled()" },
        ],
      },
    ],
  };
  decorateJournalMarkdown()(tree);
  expect(
    tree.children[0].children.map((node) =>
      node.type === "inlineCode" ? node.value : "",
    ),
  ).toEqual([
    "",
    "/home/felipe/.codex/config.toml",
    "",
    "parseTurn()",
    "",
    "alreadyStyled()",
  ]);
});
