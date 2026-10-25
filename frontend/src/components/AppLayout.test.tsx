import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/renderWithProviders";
import AppLayout from "./AppLayout";

const viewport = vi.hoisted(() => ({ mobile: false }));
vi.mock("@mui/material", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@mui/material")>()),
  useMediaQuery: () => viewport.mobile,
}));
vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({ user: { email: "test@example.com" }, signOut: vi.fn() }),
}));
vi.mock("../hooks/useConversationsContext", () => ({
  useConversationsContext: () => ({
    conversations: [],
    selectedId: null,
    selectConversation: vi.fn(),
    createConversation: vi.fn(),
    removeConversation: vi.fn(),
  }),
}));
vi.mock("./FolderTree", () => ({
  default: () => <button data-folder-navigation>Project folder</button>,
}));
vi.mock("./FolderIntegrationsDialog", () => ({ default: () => null }));

beforeEach(() => {
  viewport.mobile = false;
  Object.defineProperty(window, "localStorage", {
    value: { getItem: () => null, setItem: vi.fn(), clear: vi.fn() },
    configurable: true,
  });
});
describe("responsive application workspace", () => {
  it("gives Chat its full reading area without the global breadcrumb bar", () => {
    renderWithProviders(
      <AppLayout>
        <h1>Chat workspace</h1>
      </AppLayout>
    );
    expect(screen.queryByTestId("app-topbar")).not.toBeInTheDocument();
    expect(screen.getByTestId("context-panel")).toBeVisible();
  });

  it("keeps the folder navigator beside the menu on desktop", () => {
    renderWithProviders(
      <AppLayout>
        <h1>Documents workspace</h1>
      </AppLayout>,
      { initialEntries: ["/documents"] }
    );
    expect(
      screen.getByRole("navigation", { name: "Main navigation" })
    ).toBeVisible();
    expect(screen.getByTestId("context-panel")).toBeVisible();
    expect(
      within(screen.getByRole("main")).getByRole("heading", {
        name: "Documents workspace",
      })
    ).toBeVisible();
  });
  it("opens and closes the mobile folder navigator without replacing the workspace", async () => {
    viewport.mobile = true;
    const user = userEvent.setup();
    renderWithProviders(
      <AppLayout>
        <h1>Documents workspace</h1>
      </AppLayout>,
      { initialEntries: ["/documents"] }
    );
    expect(screen.queryByTestId("context-panel")).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Open folder navigator" })
    );
    expect(screen.getByTestId("context-panel")).toBeVisible();
    await user.click(screen.getByText("Project folder"));
    expect(
      screen.getByRole("heading", { name: "Documents workspace" })
    ).toBeVisible();
  });
  it("does not leave a folder sidebar on Settings or Remotes", () => {
    renderWithProviders(
      <AppLayout>
        <h1>Settings workspace</h1>
      </AppLayout>,
      { initialEntries: ["/settings"] }
    );
    expect(screen.queryByTestId("context-panel")).not.toBeInTheDocument();
  });
});
