import { expect, it } from "vitest";
import { codeCitationPreview } from "./codeCitationPreview";

it("focuses a contiguous original window around the claim's enum variant", () => {
  const source =
    "pub enum EventPayload {\n    StateChange { state: EventStatus },\n" +
    Array.from({ length: 25 }, (_, i) => `    Unrelated${i},`).join("\n") +
    "\n    PowerPlayStart {\n        advantage: String,\n    },\n}";
  const preview = codeCitationPreview(
    source,
    "Power-play payload: one field, advantage: String",
  );
  expect(preview).toContain("PowerPlayStart {\n        advantage: String,");
  expect(preview).not.toContain("StateChange");
  expect(preview.startsWith("…\n")).toBe(true);
  expect(source).toContain(preview.replace(/^…\n/, "").replace(/\n…$/, ""));
});

it("keeps a bounded original preview when no claim term matches", () => {
  expect(
    codeCitationPreview("fn actual() {\n    do_work();\n}", "unrelated claim"),
  ).toBe("fn actual() {\n    do_work();\n}");
});
