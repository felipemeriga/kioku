import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
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
  const saved = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    value: {
      getItem: (key: string) => saved.get(key) ?? null,
      setItem: (key: string, value: string) => saved.set(key, value),
      clear: () => saved.clear(),
    },
    configurable: true,
  });
});
describe("responsive application workspace", () => {
  it("gives Chat its full reading area without the global breadcrumb bar", () => {
    renderWithProviders(
      <AppLayout>
        <h1>Chat workspace</h1>
      </AppLayout>,
    );
    expect(screen.queryByTestId("app-topbar")).not.toBeInTheDocument();
    expect(screen.getByTestId("context-panel")).toBeVisible();
  });

  it("keeps the folder navigator beside the menu on desktop", () => {
    renderWithProviders(
      <AppLayout>
        <h1>Documents workspace</h1>
      </AppLayout>,
      { initialEntries: ["/documents"] },
    );
    expect(
      screen.getByRole("navigation", { name: "Main navigation" }),
    ).toBeVisible();
    expect(screen.getByTestId("context-panel")).toBeVisible();
    expect(
      within(screen.getByRole("main")).getByRole("heading", {
        name: "Documents workspace",
      }),
    ).toBeVisible();
  });
  it("classifies original transcript routes as Documents without a folder sidebar", () => {
    renderWithProviders(
      <AppLayout>
        <h1>Original transcript</h1>
      </AppLayout>,
      { initialEntries: ["/folders/repo/agent-sessions/archive-id"] },
    );
    expect(
      within(screen.getByTestId("app-topbar")).getByText("Documents"),
    ).toBeVisible();
    expect(screen.queryByTestId("context-panel")).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Original transcript" }),
    ).toBeVisible();
  });
  it("opens and closes the mobile folder navigator without replacing the workspace", async () => {
    viewport.mobile = true;
    const user = userEvent.setup();
    renderWithProviders(
      <AppLayout>
        <h1>Documents workspace</h1>
      </AppLayout>,
      { initialEntries: ["/documents"] },
    );
    expect(screen.queryByTestId("context-panel")).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Open folder navigator" }),
    );
    expect(screen.getByTestId("context-panel")).toBeVisible();
    await user.click(screen.getByText("Project folder"));
    expect(
      screen.getByRole("heading", { name: "Documents workspace" }),
    ).toBeVisible();
  });
  it("collapses the rail and contextual panel together, restores focus and saved width", async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <AppLayout>
        <h1>Documents workspace</h1>
      </AppLayout>,
      { initialEntries: ["/documents"] },
    );
    const separator = screen.getByRole("separator", { name: "Resize folders" });
    fireEvent.keyDown(separator, { key: "Home" });
    expect(separator).toHaveAttribute("aria-valuenow", "140");
    await user.click(
      within(screen.getByRole("navigation")).getByRole("button", {
        name: "Collapse navigation",
      }),
    );
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.queryByTestId("context-panel")).not.toBeInTheDocument();
    const reopen = screen.getByRole("button", { name: "Show navigation" });
    await waitFor(() => expect(reopen).toHaveFocus());
    await user.click(reopen);
    expect(screen.getByRole("navigation")).toBeVisible();
    expect(
      screen.getByRole("separator", { name: "Resize folders" }),
    ).toHaveAttribute("aria-valuenow", "140");
  });

  it("restores full navigation collapse after a reload", async () => {
    localStorage.setItem("kioku:panels:v1:navigationCollapsed", "true");
    renderWithProviders(
      <AppLayout>
        <h1>Chat workspace</h1>
      </AppLayout>,
    );
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.queryByTestId("context-panel")).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: "Show navigation" }),
    );
    expect(screen.getByRole("navigation")).toBeVisible();
    expect(localStorage.getItem("kioku:panels:v1:navigationCollapsed")).toBe(
      "false",
    );
  });

  it("keeps mobile navigation as a drawer and supports full collapse/reopen", async () => {
    viewport.mobile = true;
    const user = userEvent.setup();
    renderWithProviders(
      <AppLayout>
        <h1>Documents workspace</h1>
      </AppLayout>,
      { initialEntries: ["/documents"] },
    );
    await user.click(
      within(screen.getByRole("navigation")).getByRole("button", {
        name: "Collapse navigation",
      }),
    );
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show navigation" }));
    expect(screen.getByTestId("context-panel")).toBeVisible();
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
  });

  it("does not leave a folder sidebar on Settings or Remotes", () => {
    renderWithProviders(
      <AppLayout>
        <h1>Settings workspace</h1>
      </AppLayout>,
      { initialEntries: ["/settings"] },
    );
    expect(screen.queryByTestId("context-panel")).not.toBeInTheDocument();
  });
});
