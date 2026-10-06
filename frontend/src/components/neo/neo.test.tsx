import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import theme from "../../theme";
import StatusGlyph from "./StatusGlyph";
import KatakanaAccent from "./KatakanaAccent";
import CornerCard from "./CornerCard";
import SectionRail from "./SectionRail";
import PillChain from "./PillChain";
import PipelineBar from "./PipelineBar";
import RerankBar from "./RerankBar";
import StageTabs from "./StageTabs";
import RetroSun from "./RetroSun";

const wrap = (ui: React.ReactElement) =>
  render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);

describe("neo primitives", () => {
  it("StatusGlyph renders the glyph for a status", () => {
    wrap(<StatusGlyph status="pinned" />);
    expect(screen.getByText("●")).toBeInTheDocument();
  });
  it("StatusGlyph hybrid uses ◐", () => {
    wrap(<StatusGlyph status="hybrid" />);
    expect(screen.getByText("◐")).toBeInTheDocument();
  });
  it("KatakanaAccent renders its text and is aria-hidden", () => {
    const { container } = wrap(<KatakanaAccent text="記憶" />);
    expect(container.querySelector('[aria-hidden="true"]')?.textContent).toBe(
      "記憶"
    );
  });
  it("CornerCard renders children", () => {
    wrap(<CornerCard>hello</CornerCard>);
    expect(screen.getByText("hello")).toBeInTheDocument();
  });
  it("SectionRail lists section titles and calls onSelect", () => {
    const items = [
      { n: "01", title: "Overview", status: "pinned" as const },
      { n: "02", title: "Architecture", status: "auto" as const },
    ];
    let picked = -1;
    wrap(
      <SectionRail
        items={items}
        activeIndex={0}
        onSelect={(i) => (picked = i)}
      />
    );
    expect(screen.getByText("Overview")).toBeInTheDocument();
    screen.getByText("Architecture").click();
    expect(picked).toBe(1);
  });
  it("PillChain renders its steps", () => {
    wrap(
      <PillChain
        label="VIDEO PIPELINE"
        color="#FF2E93"
        steps={["A", "B", "C"]}
      />
    );
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText("C")).toBeInTheDocument();
  });
  it("PipelineBar renders the file name and stage labels", () => {
    wrap(
      <PipelineBar
        name="a.pdf"
        status={{ label: "Done", color: "#39FF14" }}
        stages={[
          { label: "UPLOAD", pct: 100, color: "#39FF14" },
          { label: "STORE", pct: 0, color: "#2A1758" },
        ]}
      />
    );
    expect(screen.getByText("a.pdf")).toBeInTheDocument();
    expect(screen.getByText("UPLOAD")).toBeInTheDocument();
  });
  it("RerankBar shows the rounded score", () => {
    wrap(<RerankBar file="doc.md" score={0.9101} />);
    expect(screen.getByText(/0\.910/)).toBeInTheDocument();
  });
  it("StageTabs highlights the active stage label", () => {
    wrap(<StageTabs active="analyzing" detail="8 docs" />);
    expect(screen.getByText("分析")).toBeInTheDocument();
  });
  it("RetroSun is aria-hidden and renders in the DOM", () => {
    const { container } = wrap(<RetroSun />);
    const el = container.querySelector('[aria-hidden="true"]');
    expect(el).not.toBeNull();
  });
});
