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
