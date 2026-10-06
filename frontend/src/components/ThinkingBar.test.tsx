// frontend/src/components/ThinkingBar.test.tsx
import { describe, it, expect } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "../test/renderWithProviders";
import ThinkingBar from "./ThinkingBar";

describe("ThinkingBar", () => {
  it("renders nothing when stage is null", () => {
    const { container } = renderWithProviders(<ThinkingBar stage={null} />);
    expect(container.querySelector('[data-testid="thinking-bar"]')).toBeNull();
  });

  it("renders the StageTabs pipeline with all stage labels", () => {
    renderWithProviders(<ThinkingBar stage={{ stage: "thinking" }} />);
    // StageTabs always renders every stage label (JP glyph).
    expect(screen.getByText("思考")).toBeInTheDocument();
    expect(screen.getByText("探索")).toBeInTheDocument();
    expect(screen.getByText("分析")).toBeInTheDocument();
    expect(screen.getByText("生成")).toBeInTheDocument();
  });

  it("renders the searching stage", () => {
    renderWithProviders(<ThinkingBar stage={{ stage: "searching" }} />);
    // 探索 = Searching
    expect(screen.getByText("探索")).toBeInTheDocument();
    expect(screen.getByText(/Searching/)).toBeInTheDocument();
  });

  it("renders the analyzing stage with its doc-count detail", () => {
    renderWithProviders(
      <ThinkingBar stage={{ stage: "analyzing", docs: 4 }} />
    );
    // 分析 = Analyzing; the active tab appends the doc count as detail.
    expect(screen.getByText("分析")).toBeInTheDocument();
    expect(screen.getByText(/Analyzing · 4 docs/)).toBeInTheDocument();
  });

  it("renders the generating stage", () => {
    renderWithProviders(<ThinkingBar stage={{ stage: "generating" }} />);
    // 生成 = Generating
    expect(screen.getByText("生成")).toBeInTheDocument();
    expect(screen.getByText(/Generating/)).toBeInTheDocument();
  });

  it("does not render a doc-count detail when there are no docs", () => {
    renderWithProviders(<ThinkingBar stage={{ stage: "searching" }} />);
    // Active tab (探索) shows just its English label, no " · N docs".
    expect(screen.getByText(/Searching/)).toBeInTheDocument();
    expect(screen.queryByText(/docs/)).toBeNull();
  });
});
