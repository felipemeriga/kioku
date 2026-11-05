import { describe, it, expect } from "vitest";
import { emptyHistoryFilters, validateHistoryFilters } from "./historySearch";
describe("History search allowed inputs", () => {
  it("accepts all supported modes, agents and session identifiers", () => {
    for (const mode of ["words", "phrase", "regex"] as const)
      for (const agent of ["", "codex", "claude_code"])
        expect(
          validateHistoryFilters({
            ...emptyHistoryFilters,
            mode,
            agent,
            q: "sdk.*",
            session_id: "01a1a9d5_5ymlz.cxvh.cosm.link",
            date_from: "2024-02-29",
          })
        ).toEqual({});
  });
  it.each([
    { q: "x".repeat(161) },
    { q: "bad\nquery" },
    { session_id: "../session/name" },
    { session_id: "x".repeat(257) },
    { date_from: "2026-02-29" },
    { date_to: "20261105" },
    { date_from: "2026-11-05", date_to: "2026-11-04" },
    { mode: "regex" as const, q: "(.*)+bad" },
  ])("rejects invalid input %j", (value) =>
    expect(
      Object.keys(validateHistoryFilters({ ...emptyHistoryFilters, ...value }))
        .length
    ).toBeGreaterThan(0)
  );
});
