import { describe, expect, it } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "../../test/renderWithProviders";
import { ReadableContent } from "./ReadableContent";
import {
  filePresentation,
  previewableText,
  readableBlocks,
} from "./contentBlocks";

describe("shared readable agent content", () => {
  it("renders journal prose, lists, inline code and mature Rust/JSON fences together", () => {
    const rust =
      "fn name(value: ItemInfo<'_>) -> Option<String> {\n    None\n}\n";
    const { container } = renderWithProviders(
      <ReadableContent
        text={`## Check results\n\n- Kept \`raw.json\` unchanged.\n\n\`\`\`rust\n${rust}\`\`\`\n\nA structured value follows.\n\n\`\`\`json\n{"count": 2}\n\`\`\``}
      />
    );
    expect(
      screen.getByRole("heading", { name: "Check results" })
    ).toBeInTheDocument();
    expect(container.querySelector("li code")).toHaveTextContent("raw.json");
    expect(container.querySelector("code.language-rust")?.textContent).toBe(
      rust
    );
    expect(
      container.querySelector("code.language-rust .token.keyword")
    ).not.toBeNull();
    expect(
      container.querySelector("code.language-json")?.textContent
    ).toContain('"count": 2');
  });

  it("keeps HTML inert, blocks unsafe links and does not request remote images", () => {
    const { container } = renderWithProviders(
      <ReadableContent
        text={
          "<script>window.bad = true</script>\n\n[unsafe](javascript:alert%281%29) [safe](https://example.test/evidence)\n\n![diagram](https://example.test/tracker.png)"
        }
      />
    );
    expect(container.querySelector("script, iframe, img")).toBeNull();
    expect(screen.queryByRole("link", { name: "unsafe" })).toBeNull();
    expect(screen.getByRole("link", { name: "safe" })).toHaveAttribute(
      "rel",
      "noopener noreferrer"
    );
    expect(screen.getByText("Image: diagram (not loaded)")).toBeInTheDocument();
  });

  it("segments conservative unfenced source without changing its surrounding terminal text", () => {
    const text =
      'src:\n-rw-r--r-- sample.rs\nuse std::path::PathBuf;\n\nfn run() {\n    println!("value {}", 2);\n}\nabc1234 example commit\n';
    const blocks = readableBlocks(text, "terminal");
    expect(blocks.map((block) => block.kind)).toEqual([
      "terminal",
      "code",
      "terminal",
    ]);
    expect(blocks.map((block) => block.text).join("")).toBe(text);
    expect(blocks[1].language).toBe("rust");
    expect(readableBlocks("use the API;\nThis is prose.\n")).toEqual([
      { kind: "markdown", text: "use the API;\nThis is prose.\n" },
    ]);
  });

  it("never treats clipped fragments as complete JSON or hides application fields", () => {
    const original = '{"output":"retained","other":3}';
    expect(readableBlocks(original, "json", false)).toEqual([
      { kind: "text", text: original },
    ]);
    expect(readableBlocks('{"output":', "json")).toEqual([
      { kind: "text", text: '{"output":' },
    ]);
    expect(readableBlocks(original, "json")[0].text).toContain('"other": 3');
  });

  it("selects safe file presentations without embedding active documents", () => {
    expect(filePresentation("notes.md", "text/plain")).toEqual({
      kind: "markdown",
    });
    expect(filePresentation("sample.rs", "application/octet-stream")).toEqual({
      kind: "code",
      language: "rust",
    });
    expect(filePresentation("value.json", "application/json")).toEqual({
      kind: "json",
      language: "json",
    });
    expect(filePresentation("page.html", "text/html")).toEqual({
      kind: "code",
      language: "markup",
    });
    expect(previewableText("sample.rs", "application/octet-stream")).toBe(true);
    expect(previewableText("archive.zip", "application/zip")).toBe(false);
  });
});
