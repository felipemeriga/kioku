import { beforeEach, describe, expect, it, vi } from "vitest";
import * as ReactQuery from "@tanstack/react-query";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/renderWithProviders";
import { getRemoteMachines, renameRemoteMachine } from "../lib/api";
import RemotesPage from "./RemotesPage";
vi.mock("@tanstack/react-query", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@tanstack/react-query")>();
  return { ...actual, useQuery: vi.fn(actual.useQuery) };
});
vi.mock("../lib/supabase", () => ({
  supabase: { auth: { getSession: vi.fn() } },
}));
vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/api")>()),
  getRemoteMachines: vi.fn(),
  renameRemoteMachine: vi.fn(),
}));
const machine = {
  id: "one",
  name: "My Mac",
  platform: "darwin-arm64",
  version: "0.4.0",
  created_at: "2026-10-24T10:00:00Z",
  connected_at: "2026-10-24T11:00:00Z",
  last_seen: "2026-10-24T11:00:00Z",
  online: true,
};
beforeEach(() =>
  vi.mocked(getRemoteMachines).mockResolvedValue([
    machine,
    {
      ...machine,
      id: "two",
      name: "Linux box",
      platform: "linux-x64",
      online: false,
    },
  ])
);
describe("Remotes connection", () => {
  it("renders real machine presence without invented memory stats", async () => {
    renderWithProviders(<RemotesPage />);
    expect(
      await screen.findByRole("heading", { name: "My Mac" })
    ).toBeInTheDocument();
    expect(screen.getByText("1 online")).toBeInTheDocument();
    expect(screen.getByText("1 offline")).toBeInTheDocument();
    expect(
      screen.getByText(/Memory collection is not enabled/)
    ).toBeInTheDocument();
    expect(screen.queryByText(/imported/)).not.toBeInTheDocument();
  });
  it("switches machines and shows offline reconnection guidance", async () => {
    const user = userEvent.setup();
    renderWithProviders(<RemotesPage />);
    await user.click(await screen.findByRole("button", { name: /Linux box/ }));
    expect(
      screen.getByRole("heading", { name: "This machine is offline" })
    ).toBeInTheDocument();
  });
  it("filters and recovers an empty search", async () => {
    const user = userEvent.setup();
    renderWithProviders(<RemotesPage />);
    await screen.findByRole("heading", { name: "My Mac" });
    const search = screen.getByRole("textbox", { name: "Find a machine" });
    await user.type(search, "unmatched");
    expect(screen.getByText(/No machines match/)).toBeInTheDocument();
    await user.clear(search);
    expect(screen.getByRole("heading", { name: "My Mac" })).toBeInTheDocument();
  });
  it("shows empty-state automatic init instructions", async () => {
    vi.mocked(getRemoteMachines).mockResolvedValue([]);
    const user = userEvent.setup();
    renderWithProviders(<RemotesPage />);
    expect(
      await screen.findByRole("heading", { name: "Connect your first machine" })
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Connect machine" }));
    expect(screen.getByRole("dialog")).toHaveTextContent(
      "automatically installs and starts one Manabi"
    );
  });
  it("surfaces load failures without claiming a successful connection", async () => {
    vi.mocked(ReactQuery.useQuery).mockReturnValueOnce({
      data: undefined,
      isError: true,
      error: new Error("Backend unavailable"),
      isPending: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof ReactQuery.useQuery>);
    renderWithProviders(<RemotesPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Backend unavailable"
    );
    expect(
      screen.getByRole("heading", { name: "Machines unavailable" })
    ).toBeInTheDocument();
    expect(
      screen.queryByText("No machines connected yet.")
    ).not.toBeInTheDocument();
  });
});

it("marks previously loaded machine status unknown when refresh fails", () => {
  vi.mocked(ReactQuery.useQuery).mockReturnValueOnce({
    data: [machine],
    isError: true,
    error: new Error("Backend unavailable"),
    isPending: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof ReactQuery.useQuery>);
  renderWithProviders(<RemotesPage />);
  expect(
    screen.getByRole("button", { name: /My Mac.*Unknown/ })
  ).toBeInTheDocument();
  expect(screen.getByText("Status unavailable")).toBeInTheDocument();
  expect(screen.queryByText("1 online")).not.toBeInTheDocument();
});

it("shows initialized repositories and both configured providers with actual OS labels", async () => {
  vi.mocked(getRemoteMachines).mockResolvedValue([
    {
      ...machine,
      os_name: "macOS",
      os_id: "macos",
      architecture: "arm64",
      inventory_updated_at: machine.last_seen,
      inventory: [
        {
          id: "repo",
          folder_id: "folder-one",
          name: "kioku",
          path: "/home/felipe/kioku",
          agents: ["claude", "codex"],
          initialized_at: machine.created_at,
          available: true,
        },
      ],
    },
  ]);
  renderWithProviders(<RemotesPage />);
  expect(await screen.findByRole("link", { name: "kioku" })).toHaveAttribute(
    "href",
    "/documents?folder=folder-one"
  );
  expect(screen.getByText("/home/felipe/kioku")).toBeInTheDocument();
  expect(screen.getByText("✳ Claude Code")).toBeInTheDocument();
  expect(screen.getByText("›_ Codex")).toBeInTheDocument();
  expect(
    screen.getByText(
      "Configured providers · activity detection is not enabled."
    )
  ).toBeInTheDocument();
  expect(
    screen.queryByRole("heading", { name: "Configured agents" })
  ).not.toBeInTheDocument();
  expect(screen.getAllByText("macOS")).toHaveLength(2);
  expect(screen.queryByText("Running")).not.toBeInTheDocument();
});

it("shows timestamped last-known warnings separately from offline presence", async () => {
  vi.mocked(getRemoteMachines).mockResolvedValue([
    {
      ...machine,
      online: false,
      warnings: [{ code: "repo_unavailable", observed_at: machine.last_seen }],
    },
  ]);
  renderWithProviders(<RemotesPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "repository path is unavailable"
  );
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Last known report; machine is offline"
  );
  expect(
    screen.getByRole("heading", { name: "This machine is offline" })
  ).toBeInTheDocument();
});

it("saves an optional machine name without changing its registration", async () => {
  vi.mocked(renameRemoteMachine).mockResolvedValue({
    ...machine,
    name: "Office Mac",
    custom_name: "Office Mac",
  });
  const user = userEvent.setup();
  renderWithProviders(<RemotesPage />);
  await screen.findByRole("heading", { name: "My Mac" });
  await user.click(screen.getByRole("button", { name: "Rename" }));
  const name = screen.getByRole("textbox", { name: "Machine name" });
  await user.clear(name);
  await user.type(name, "Office Mac");
  await user.click(screen.getByRole("button", { name: "Save" }));
  await waitFor(() =>
    expect(renameRemoteMachine).toHaveBeenCalledWith("one", "Office Mac")
  );
});
