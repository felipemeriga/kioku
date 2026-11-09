import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { renderWithProviders } from "../../test/renderWithProviders";
import EvidenceDrawer from "./EvidenceDrawer";
const viewport = vi.hoisted(() => ({ mobile: false }));
vi.mock("@mui/material", async (original) => ({
  ...(await original<typeof import("@mui/material")>()),
  useMediaQuery: () => viewport.mobile,
}));
vi.mock("./TranscriptViewer", () => ({
  default: () => (
    <section aria-label="Original transcript">Source records</section>
  ),
}));
const location = {
  folderId: "repo",
  sessionId: "session",
  mode: "conversation" as const,
  timezone: "UTC",
  date: "2026-11-09",
};
beforeEach(() => {
  viewport.mobile = false;
  Object.defineProperty(window, "localStorage", {
    value: { getItem: () => null, setItem: vi.fn() },
    configurable: true,
  });
});
it("resizes originals down to280px without changing their route or reader", () => {
  renderWithProviders(
    <EvidenceDrawer
      location={location}
      onLocationChange={vi.fn()}
      onClose={vi.fn()}
    />,
  );
  const handle = screen.getByRole("separator", {
    name: "Resize original transcript",
  });
  fireEvent.keyDown(handle, { key: "Home" });
  expect(handle).toHaveAttribute("aria-valuenow", "280");
  fireEvent.keyDown(handle, { key: "ArrowLeft", shiftKey: true });
  expect(handle).toHaveAttribute("aria-valuenow", "312");
  expect(
    screen.getByRole("region", { name: "Original transcript" }),
  ).toBeVisible();
  expect(
    screen.getByRole("link", { name: "Open full transcript" }),
  ).toHaveAttribute(
    "href",
    expect.stringContaining("/folders/repo/agent-sessions/session"),
  );
});
it("uses full-width mobile originals without a draggable divider", () => {
  viewport.mobile = true;
  renderWithProviders(
    <EvidenceDrawer
      location={location}
      onLocationChange={vi.fn()}
      onClose={vi.fn()}
    />,
  );
  expect(screen.queryByRole("separator")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Close evidence" })).toBeVisible();
});
