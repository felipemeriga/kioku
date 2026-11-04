import { describe, it, expect, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "../test/renderWithProviders";
import InspectDialog from "./InspectDialog";
import { fetchToolArtifact, type DebugToolCall } from "../lib/api";

vi.mock("../lib/api", () => ({ fetchToolArtifact: vi.fn() }));

function show(tool_calls: DebugToolCall[]) {
  renderWithProviders(
    <InspectDialog
      open
      onClose={vi.fn()}
      trace={{ reasoning: [], retrieval: [], tool_calls }}
    />,
  );
  fireEvent.click(
    screen.getByRole("tab", { name: /Tool calls|Retrieval and tools/ }),
  );
}

describe("retrieval provenance", () => {
  it("distinguishes host retrieval, preserves query and selected file scope", () => {
    show([
      {
        name: "knowledge_base_search",
        origin: "backend_retrieval",
        input: { query: "output modes and dry-run" },
        effective_scope: {
          user_id: "owner",
          folder_ids: ["folder"],
          filename: "guide.md",
        },
      },
    ]);
    expect(screen.getByText("Backend retrieval")).toBeInTheDocument();
    expect(screen.getByText(/output modes and dry-run/)).toBeInTheDocument();
    expect(screen.queryByText(/guide.md/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: "Retrieval and tools (1)" }),
    ).toBeInTheDocument();
  });
  it("labels bootstrap honestly and supports historical query-only traces", () => {
    show([
      {
        name: "knowledge_base_search",
        origin: "backend_bootstrap",
        query: "legacy question",
      },
    ]);
    expect(screen.getByText("Backend initial retrieval")).toBeInTheDocument();
    expect(screen.getByText(/legacy question/)).toBeInTheDocument();
  });
  it("retains exact evidence artifact access for host retrieval", async () => {
    vi.mocked(fetchToolArtifact).mockResolvedValue({
      result: "Exact backend evidence",
      trace: null,
    });
    renderWithProviders(
      <InspectDialog
        open
        onClose={vi.fn()}
        trace={{
          reasoning: [],
          retrieval: [],
          tool_calls: [
            {
              name: "knowledge_base_search",
              origin: "backend_retrieval",
              artifact_id: "artifact",
              input: { query: "guide" },
            },
          ],
          execution: { job_id: "job", turn_id: "turn" },
        }}
      />,
    );
    fireEvent.click(
      screen.getByRole("tab", { name: "Retrieval and tools (1)" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "View exact returned evidence" }),
    );
    await waitFor(() =>
      expect(fetchToolArtifact).toHaveBeenCalledWith("job", "artifact"),
    );
    expect(
      await screen.findByText("Exact backend evidence"),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Result available in the evidence artifact."),
    ).not.toBeInTheDocument();
    expect(screen.getAllByTestId("inspect-code-content")).toHaveLength(2);
    expect(screen.queryByText("Search scope")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Technical details" }),
    ).not.toBeInTheDocument();
  });
  it("preserves actual agent rounds and shows missing input explicitly", () => {
    show([
      { name: "code_graph_lookup", round: 2, input: { symbol: "run" } },
      { name: "recent_changes" },
    ]);
    expect(
      screen.getByRole("tab", { name: "Tool calls (2)" }),
    ).toBeInTheDocument();
    expect(screen.getByText("round 2")).toBeInTheDocument();
    expect(screen.getByText(/"symbol": "run"/)).toBeInTheDocument();
    expect(screen.getByText("No input recorded.")).toBeInTheDocument();
    expect(screen.queryByText("Backend retrieval")).not.toBeInTheDocument();
  });
});

it("highlights retrieved configuration chunks using their source filenames", () => {
  renderWithProviders(
    <InspectDialog
      open
      onClose={vi.fn()}
      trace={{
        reasoning: [],
        tool_calls: [],
        retrieval: [
          {
            source: "config.toml",
            source_type: "code",
            content: "[server]\nport = 8788",
          },
          {
            source: "deploy/app.yaml:1-2",
            source_type: "code",
            content: "server:\n  enabled: true",
          },
        ],
      }}
    />,
  );
  fireEvent.click(screen.getByRole("tab", { name: "Chunks (2)" }));
  expect(
    screen
      .getAllByTestId("inspect-code-content")
      .map((el) => el.dataset.language),
  ).toEqual(["toml", "yaml"]);
});

it("links code chunks to their verified GitHub source and exact line range", () => {
  renderWithProviders(
    <InspectDialog
      open
      onClose={vi.fn()}
      citations={[
        {
          number: 1,
          source: "src/schema.proto:10-20",
          source_type: "code",
          file: "src/schema.proto",
          folder_id: "repo",
          url: "https://github.com/org/repo/blob/main/src/schema.proto#L10",
          excerpt: "message Example {}",
        },
      ]}
      trace={{
        reasoning: [],
        tool_calls: [],
        retrieval: [
          {
            source: "src/schema.proto:10-20",
            source_type: "code",
            folder_id: "repo",
            content: "message Example {}",
            rerank_score: 0.8,
          },
        ],
      }}
    />,
  );
  fireEvent.click(screen.getByRole("tab", { name: "Chunks (1)" }));
  expect(
    screen.getByRole("link", { name: "src/schema.proto:10-20" }),
  ).toHaveAttribute(
    "href",
    "https://github.com/org/repo/blob/main/src/schema.proto#L10-L20",
  );
  expect(screen.getByText("Proto")).toBeInTheDocument();
  expect(screen.queryByText("PROTOBUF")).not.toBeInTheDocument();
});

it("opens document chunks in the existing preview flow", () => {
  const onClose = vi.fn();
  const onOpenDocument = vi.fn();
  renderWithProviders(
    <InspectDialog
      open
      onClose={onClose}
      onOpenDocument={onOpenDocument}
      trace={{
        reasoning: [],
        tool_calls: [],
        retrieval: [
          {
            source: "guide.pdf",
            source_type: "document",
            folder_id: "docs",
            content: "Guide",
          },
        ],
      }}
    />,
  );
  fireEvent.click(screen.getByRole("tab", { name: "Chunks (1)" }));
  fireEvent.click(screen.getByRole("button", { name: "guide.pdf" }));
  expect(onClose).toHaveBeenCalledOnce();
  expect(onOpenDocument).toHaveBeenCalledWith("guide.pdf", "docs");
});
