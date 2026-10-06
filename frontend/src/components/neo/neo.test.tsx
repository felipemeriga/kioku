import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import theme from "../../theme";
import StatusGlyph from "./StatusGlyph";
import KatakanaAccent from "./KatakanaAccent";

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
});
