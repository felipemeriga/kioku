import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { renderWithProviders } from "../test/renderWithProviders";
import * as api from "../lib/api";
import ContextPanel from "../components/ContextPanel";
import DocumentsPage from "./DocumentsPage";

vi.mock("../lib/supabase", () => ({
  supabase: { auth: { getSession: vi.fn() } },
}));
vi.mock("../components/NotionSyncBanner", () => ({
  NotionSyncBanner: () => null,
}));
vi.mock("../components/FolderIntegrationsDialog", () => ({
  default: () => null,
}));
vi.mock("../components/BriefingPanel", () => ({
  default: () => <div>Briefing content</div>,
}));
vi.mock("../components/DocumentationPanel", () => ({
  default: () => null,
}));

const parent = {
  id: "parent",
  user_id: "user",
  name: "Parent",
  parent_id: null,
  kind: "folder" as const,
  created_at: "2026-01-01",
};
const child = { ...parent, id: "child", name: "Child", parent_id: "parent" };

function Navigation({ surface }: { surface: "grid" | "tree" }) {
  const navigate = useNavigate();
  const location = useLocation();
  return (
    <>
      <button onClick={() => navigate(-1)}>Browser Back</button>
      <button onClick={() => navigate(1)}>Browser Forward</button>
      <output data-testid="location">
        {location.pathname + location.search}
      </output>
      <Routes>
        <Route path="/" element={<div>Chat page</div>} />
        <Route
          path="/documents"
          element={
            surface === "grid" ? (
              <DocumentsPage />
            ) : (
              <ContextPanel
                activePage="/documents"
                open
                conversations={[]}
                selectedConversationId={null}
                onSelectConversation={vi.fn()}
                onNewConversation={vi.fn()}
                onDeleteConversation={vi.fn()}
              />
            )
          }
        />
      </Routes>
    </>
  );
}

describe("folder browser history", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => null),
      setItem: vi.fn(),
    });
    vi.spyOn(api, "fetchFolders").mockImplementation(async (id) =>
      !id ? [parent] : id === "parent" ? [child] : [],
    );
    vi.spyOn(api, "fetchDocuments").mockResolvedValue([]);
    vi.spyOn(api, "fetchBreadcrumbs").mockImplementation(async (id) =>
      id === "child" ? [parent, child] : [parent],
    );
  });

  afterEach(() => vi.unstubAllGlobals());

  it("waits for folders before showing the empty corpus state", async () => {
    let finishFolders!: (folders: (typeof parent)[]) => void;
    vi.spyOn(api, "fetchFolders").mockImplementation(
      () =>
        new Promise((resolve) => {
          finishFolders = resolve;
        }),
    );
    renderWithProviders(<Navigation surface="grid" />, {
      initialEntries: ["/documents"],
    });
    expect(screen.queryByText("Your corpus is empty")).not.toBeInTheDocument();
    await waitFor(() => expect(finishFolders).toBeTypeOf("function"));
    act(() => finishFolders([]));
    expect(await screen.findByText("Your corpus is empty")).toBeInTheDocument();
  });

  it.each(["grid", "tree"] as const)(
    "Back/Forward restores every %s folder before leaving Documents",
    async (surface) => {
      const user = userEvent.setup();
      renderWithProviders(<Navigation surface={surface} />, {
        initialEntries: ["/", "/documents"],
      });
      await user.click(await screen.findByText("Parent"));
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/documents?folder=parent",
      );
      await user.click(await screen.findByText("Child"));
      expect(screen.getByTestId("location")).toHaveTextContent(
        "/documents?folder=child",
      );
      if (surface === "tree") await user.click(screen.getByText("Child"));

      for (const path of ["/documents?folder=parent", "/documents", "/"]) {
        await user.click(screen.getByText("Browser Back"));
        expect(screen.getByTestId("location").textContent).toBe(path);
      }
      expect(screen.getByText("Chat page")).toBeInTheDocument();
      for (const path of [
        "/documents",
        "/documents?folder=parent",
        "/documents?folder=child",
      ]) {
        await user.click(screen.getByText("Browser Forward"));
        expect(screen.getByTestId("location").textContent).toBe(path);
      }
    },
  );

  it("records breadcrumb and root navigation without duplicate current-folder entries", async () => {
    const user = userEvent.setup();
    renderWithProviders(<Navigation surface="grid" />, {
      initialEntries: ["/documents"],
    });
    await user.click(await screen.findByText("Parent"));
    await user.click(await screen.findByText("Child"));
    await user.click(await screen.findByRole("button", { name: "Parent" }));
    expect(screen.getByTestId("location").textContent).toBe(
      "/documents?folder=parent",
    );
    await user.click(screen.getByRole("button", { name: "Root" }));
    await user.click(screen.getByRole("button", { name: "Root" }));
    await user.click(screen.getByText("Browser Back"));
    expect(screen.getByTestId("location").textContent).toBe(
      "/documents?folder=parent",
    );
    await user.click(screen.getByText("Browser Back"));
    expect(screen.getByTestId("location").textContent).toBe(
      "/documents?folder=child",
    );
  });

  it("offers file drop and current repo tabs without recording or briefing history", async () => {
    const repo = {
      ...parent,
      id: "repo",
      name: "Repository",
      kind: "repo" as const,
    };
    vi.spyOn(api, "fetchFolders").mockImplementation(async (id) =>
      id ? [] : [repo],
    );
    vi.spyOn(api, "fetchBreadcrumbs").mockResolvedValue([repo]);
    renderWithProviders(<Navigation surface="grid" />, {
      initialEntries: ["/documents?folder=repo"],
    });

    expect(
      await screen.findByText("Drop files into this folder, or use Upload."),
    ).toBeInTheDocument();
    expect(
      await screen.findByRole("tab", { name: "Files" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Briefing" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Status" })).toBeInTheDocument();
    expect(
      screen.queryByRole("tab", { name: "History" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Record audio" }),
    ).not.toBeInTheDocument();
  });

  it("opens an existing briefing first while keeping Files selectable", async () => {
    const user = userEvent.setup();
    const repo = {
      ...parent,
      id: "repo",
      name: "Repository",
      kind: "repo" as const,
    };
    vi.spyOn(api, "fetchFolders").mockImplementation(async (id) =>
      id ? [] : [repo],
    );
    vi.spyOn(api, "fetchBreadcrumbs").mockResolvedValue([repo]);
    vi.spyOn(api, "fetchBriefing").mockResolvedValue({
      folder: repo,
      schema_version: 1,
      sections: {} as Awaited<ReturnType<typeof api.fetchBriefing>>["sections"],
      last_generated_at: "2026-10-29T12:00:00Z",
    });
    renderWithProviders(<Navigation surface="grid" />, {
      initialEntries: ["/documents?folder=repo"],
    });

    expect(await screen.findByText("Briefing content")).toBeInTheDocument();
    const tabs = screen.getAllByRole("tab");
    expect(tabs[0]).toHaveTextContent("Briefing");
    expect(tabs[0]).toHaveAttribute("aria-selected", "true");
    await user.click(screen.getByRole("tab", { name: "Files" }));
    expect(screen.getByRole("tab", { name: "Files" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});
