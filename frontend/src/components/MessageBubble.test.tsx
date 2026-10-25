import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "../test/renderWithProviders";
import MessageBubble from "./MessageBubble";
import type { Citation } from "../lib/api";

describe("MessageBubble", () => {
  it("bounds both roles with visible message surfaces", () => {
    renderWithProviders(
      <>
        <MessageBubble role="user" content="Question" />
        <MessageBubble role="assistant" content="Answer" />
      </>
    );
    for (const role of ["user", "assistant"]) {
      const surface = screen.getByTestId(`${role}-message-surface`);
      expect(getComputedStyle(surface).borderTopStyle).toBe("solid");
      expect(getComputedStyle(surface).borderTopWidth).toBe("1px");
    }
  });

  it("renders user message content", () => {
    renderWithProviders(<MessageBubble role="user" content="Hello world" />);
    expect(screen.getByText("Hello world")).toBeInTheDocument();
  });

  it("renders assistant message with markdown", () => {
    renderWithProviders(
      <MessageBubble role="assistant" content="**bold text**" />
    );
    expect(screen.getByText("bold text")).toBeInTheDocument();
  });

  it("shows avatar icon for assistant messages", () => {
    renderWithProviders(<MessageBubble role="assistant" content="Hello" />);
    expect(screen.getByTestId("assistant-avatar")).toBeInTheDocument();
  });

  it("does not show avatar icon for user messages", () => {
    renderWithProviders(<MessageBubble role="user" content="Hello" />);
    expect(screen.queryByTestId("assistant-avatar")).toBeNull();
  });
});

const docCite: Citation = {
  number: 1,
  source: "notes.pdf",
  source_type: "document",
  folder_id: "f1",
  url: null,
  excerpt: "a document excerpt",
};
const codeCite: Citation = {
  number: 2,
  source: "pkg/x.py:10-20",
  source_type: "code",
  file: "pkg/x.py",
  line: 10,
  symbol: "foo",
  folder_id: "f2",
  url: "https://github.com/org/repo/blob/main/pkg/x.py#L10",
  excerpt: "def foo(): ...",
};

describe("MessageBubble citations", () => {
  it("renders a chip per inline [N] and a Sources footer", () => {
    renderWithProviders(
      <MessageBubble
        role="assistant"
        content="Foo [1] bar [2]."
        citations={[docCite, codeCite]}
      />
    );
    expect(screen.getAllByTestId("citation-chip")).toHaveLength(2);
    expect(screen.getByTestId("citation-sources")).toBeInTheDocument();
    expect(screen.getAllByTestId("citation-source")).toHaveLength(2);
  });

  it("does not linkify [N] inside a code block", () => {
    renderWithProviders(
      <MessageBubble
        role="assistant"
        content={"See [1].\n\n```\narr[1] = x\n```\n"}
        citations={[docCite]}
      />
    );
    // Only the prose [1] becomes a chip; the one inside the code fence does not.
    expect(screen.getAllByTestId("citation-chip")).toHaveLength(1);
    expect(screen.getAllByTestId("citation-source")).toHaveLength(1);
  });

  it("opens a document citation via onOpenDocument", () => {
    const onOpenDocument = vi.fn();
    renderWithProviders(
      <MessageBubble
        role="assistant"
        content="Foo [1]."
        citations={[docCite]}
        onOpenDocument={onOpenDocument}
      />
    );
    fireEvent.click(screen.getByTestId("citation-chip"));
    expect(onOpenDocument).toHaveBeenCalledWith("notes.pdf", "f1");
  });

  it("opens a code citation's GitHub URL in a new tab", () => {
    const open = vi.spyOn(window, "open").mockImplementation(() => null);
    renderWithProviders(
      <MessageBubble
        role="assistant"
        content="Foo [2]."
        citations={[codeCite]}
      />
    );
    fireEvent.click(screen.getByTestId("citation-chip"));
    expect(open).toHaveBeenCalledWith(
      "https://github.com/org/repo/blob/main/pkg/x.py#L10",
      "_blank",
      "noopener,noreferrer"
    );
    open.mockRestore();
  });

  it("shows no footer when the message has no citations", () => {
    renderWithProviders(
      <MessageBubble role="assistant" content="Just text, no refs." />
    );
    expect(screen.queryByTestId("citation-sources")).toBeNull();
  });
});

describe("bounded source previews", () => {
  it("activates inline markers with Enter and Space without scrolling the page", () => {
    const open = vi.fn();
    renderWithProviders(
      <MessageBubble
        role="assistant"
        content="See [1]."
        citations={[docCite]}
        onOpenDocument={open}
      />
    );
    const marker = screen.getByTestId("citation-chip");
    expect(marker.tagName).toBe("BUTTON");
    for (const key of ["Enter", " "]) {
      const event = new KeyboardEvent("keydown", {
        key,
        bubbles: true,
        cancelable: true,
      });
      fireEvent(marker, event);
      expect(event.defaultPrevented).toBe(true);
    }
    expect(open).toHaveBeenCalledTimes(2);
    expect(open).toHaveBeenLastCalledWith("notes.pdf", "f1");
  });

  it("shows short plain-text snippets instead of raw fences and repeated whitespace", async () => {
    const excerpt = `\`\`\`typescript\nconst sample = \`safe\`;\n${"value   ".repeat(
      100
    )}\n\`\`\``;
    const { container } = renderWithProviders(
      <MessageBubble
        role="assistant"
        content="See [1]."
        citations={[{ ...docCite, excerpt }]}
      />
    );
    const snippet = container.querySelector(".source-card-excerpt")!;
    expect(snippet.textContent).toContain("const sample = safe;");
    expect(snippet.textContent).not.toMatch(/`|\n| {2}/);
    expect(snippet.textContent!.length).toBeLessThanOrEqual(220);
    expect(snippet.textContent).toMatch(/…$/);
    const marker = screen.getByTestId("citation-chip");
    vi.spyOn(marker, "getBoundingClientRect").mockReturnValue(
      new DOMRect(100, 200, 20, 20)
    );
    fireEvent.mouseOver(marker);
    const tooltip = await screen.findByRole("tooltip");
    expect(container.contains(tooltip)).toBe(false);
    expect(tooltip).toHaveTextContent("const sample = safe;");
    expect(tooltip.textContent).not.toContain("```");
    const surface = tooltip.querySelector(".MuiTooltip-tooltip") ?? tooltip;
    expect(getComputedStyle(surface).maxWidth).toContain("100vw - 32px");
  });

  it("uses the excerpt fallback for unknown document names without requesting a fake file", async () => {
    const open = vi.fn();
    renderWithProviders(
      <MessageBubble
        role="assistant"
        content="See [1]."
        citations={[
          {
            ...docCite,
            source: "unknown",
            excerpt: "A verified retrieved excerpt.",
          },
        ]}
        onOpenDocument={open}
      />
    );
    fireEvent.click(screen.getByTestId("citation-chip"));
    expect(open).not.toHaveBeenCalled();
    expect(await screen.findByRole("dialog")).toHaveTextContent(
      "Retrieved source"
    );
    expect(screen.getByTestId("source-excerpt-text")).toHaveTextContent(
      "A verified retrieved excerpt."
    );
  });

  it("opens an excerpt on touch or click when a code source has no deep link", async () => {
    renderWithProviders(
      <MessageBubble
        role="assistant"
        content="See [2]."
        citations={[{ ...codeCite, url: null }]}
      />
    );
    fireEvent.click(screen.getByTestId("citation-source"));
    expect(await screen.findByRole("dialog")).toHaveTextContent(
      "Retrieved code excerpt"
    );
    expect(screen.getByTestId("source-excerpt-text")).toHaveTextContent(
      "def foo(): ..."
    );
  });

  it("keeps wide code scrolling inside its own bounded surface", () => {
    const longUrl = `https://example.test/${"path".repeat(200)}`;
    const { container } = renderWithProviders(
      <MessageBubble
        role="assistant"
        content={`${longUrl}\n\n\`inline-${"value".repeat(
          80
        )}\`\n\n\`\`\`text\n${longUrl}\n\`\`\``}
      />
    );
    const pre = container.querySelector("pre")!;
    expect(getComputedStyle(pre).maxWidth).toBe("100%");
    expect(getComputedStyle(pre).overflowX).toBe("auto");
    expect(getComputedStyle(pre).whiteSpace).toBe("pre");
    expect(
      getComputedStyle(screen.getByTestId("assistant-message-surface")).minWidth
    ).toBe("0px");
  });
});
