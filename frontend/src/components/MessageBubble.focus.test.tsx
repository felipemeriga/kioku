import { expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "../test/renderWithProviders";
import { fetchToolArtifact } from "../lib/api";
import MessageBubble from "./MessageBubble";
vi.mock("../lib/api", async (original) => ({
  ...(await original<object>()),
  fetchToolArtifact: vi.fn(),
}));

it("loads cached exact evidence only on hover and previews the relevant variant", async () => {
  const code =
    "pub enum EventPayload {\n    StateChange { state: EventStatus },\n" +
    Array.from({ length: 25 }, (_, i) => `    Other${i},`).join("\n") +
    "\n    PowerPlayStart {\n        advantage: String,\n    },\n}";
  vi.mocked(fetchToolArtifact).mockResolvedValue({
    result: code,
    trace: {
      sources: [
        { source: "event.rs:437-555", folder_id: "repo", content: code },
      ],
    },
  });
  renderWithProviders(
    <MessageBubble
      role="assistant"
      content="**Power-play payload:** one field, `advantage: String` [1]."
      citations={[
        {
          number: 1,
          source: "event.rs:437-555",
          file: "event.rs",
          source_type: "code",
          folder_id: "repo",
          excerpt: code.slice(0, 100),
        },
      ]}
      debug={{
        reasoning: [],
        execution: { job_id: "job", turn_id: "turn" },
        tool_calls: [
          {
            name: "knowledge_base_search",
            artifact_id: "artifact",
            input: { query: "power play" },
          },
        ],
        retrieval: [
          {
            source: "event.rs:437-555",
            source_type: "code",
            folder_id: "repo",
            query: "power play",
            content: code.slice(0, 100),
          },
        ],
      }}
    />,
  );
  expect(fetchToolArtifact).not.toHaveBeenCalled();
  fireEvent.mouseOver(screen.getByTestId("citation-chip"));
  await waitFor(() =>
    expect(screen.getByTestId("citation-preview").textContent).toContain(
      "PowerPlayStart",
    ),
  );
  expect(screen.getByTestId("citation-preview").textContent).toContain(
    "advantage: String",
  );
  expect(screen.getByTestId("citation-preview").textContent).not.toContain(
    "StateChange",
  );
  expect(fetchToolArtifact).toHaveBeenCalledTimes(1);
  expect(fetchToolArtifact).toHaveBeenCalledWith("job", "artifact");
});
