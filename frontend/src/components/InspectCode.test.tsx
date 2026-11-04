import { expect, it } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import InspectCode from "./InspectCode";
import { renderWithProviders } from "../test/renderWithProviders";

it("pretty-prints JSON while retaining the exact raw evidence", () => {
  const original = '{"attempts":3,"nested":{"enabled":true}}';
  renderWithProviders(<InspectCode>{original}</InspectCode>);
  const block = screen.getByTestId("inspect-code-content");
  expect(block.dataset.language).toBe("json");
  expect(block.querySelector("code")?.textContent).toBe(
    JSON.stringify(JSON.parse(original), null, 2),
  );
  fireEvent.click(screen.getByRole("button", { name: "Show raw text" }));
  expect(block.querySelector("code")?.textContent).toBe(original);
  expect(block.dataset.language).toBe("text");
});

it.each([
  ["config.toml:1-5", "toml", '[server]\nport = 8788\nname = "tsukai"'],
  ["deploy/app.yaml", "yaml", "server:\n  port: 8788\n  enabled: true"],
])(
  "formats %s without rewriting its values or whitespace",
  (filename, language, content) => {
    renderWithProviders(
      <InspectCode filename={filename}>{content}</InspectCode>,
    );
    const block = screen.getByTestId("inspect-code-content");
    expect(block.dataset.language).toBe(language);
    expect(block.querySelector("code")?.textContent).toBe(content);
  },
);

it("keeps all lines of a retrieved source chunk", () => {
  const code = Array.from(
    { length: 30 },
    (_, i) => `    fn item_${i}() {}`,
  ).join("\n");
  renderWithProviders(
    <InspectCode filename="src/main.rs:10-39">{code}</InspectCode>,
  );
  expect(screen.getByTestId("inspect-code-content").dataset.language).toBe(
    "rust",
  );
  expect(
    screen.getByTestId("inspect-code-content").querySelector("code")
      ?.textContent,
  ).toBe(code);
});

it("recognizes fenced YAML and can show the original fences", () => {
  const content = "```yaml\nserver:\n  enabled: true\n```";
  renderWithProviders(<InspectCode>{content}</InspectCode>);
  expect(screen.getByTestId("inspect-code-content").dataset.language).toBe(
    "yaml",
  );
  expect(screen.getByTestId("inspect-code-content").textContent).not.toContain(
    "```",
  );
  fireEvent.click(screen.getByRole("button", { name: "Show raw text" }));
  expect(screen.getByTestId("inspect-code-content").textContent).toBe(content);
});

it("leaves malformed JSON intact", () => {
  const content = '{"unfinished":';
  renderWithProviders(<InspectCode language="json">{content}</InspectCode>);
  expect(screen.getByTestId("inspect-code-content").textContent).toBe(content);
});
