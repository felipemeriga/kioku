import { describe, it, expect } from "vitest";
import { serializeSection } from "./serializeSection";

describe("serializeSection", () => {
  it("renders object fields one per line, sorted", () => {
    expect(serializeSection({ purpose: "p", description: "d" })).toBe(
      "description: d\npurpose: p"
    );
  });
  it("renders arrays as bullet lines", () => {
    expect(serializeSection(["a", "b"])).toBe("- a\n- b");
  });
  it("renders a bare string as itself", () => {
    expect(serializeSection("hello")).toBe("hello");
  });
});
