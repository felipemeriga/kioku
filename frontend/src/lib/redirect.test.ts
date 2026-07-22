import { describe, it, expect } from "vitest";
import { safeRedirect } from "./redirect";

describe("safeRedirect", () => {
  it("allows same-origin relative paths", () => {
    expect(safeRedirect("/cli-auth?req=abc")).toBe("/cli-auth?req=abc");
  });
  it("rejects protocol-relative and absolute urls", () => {
    expect(safeRedirect("//evil.com")).toBe("/");
    expect(safeRedirect("https://evil.com")).toBe("/");
    expect(safeRedirect("http://evil.com")).toBe("/");
  });
  it("rejects null / non-slash", () => {
    expect(safeRedirect(null)).toBe("/");
    expect(safeRedirect("evil")).toBe("/");
  });
});
