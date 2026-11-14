import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { renderWithProviders } from "../test/renderWithProviders";
import RootAccessPage from "./RootAccessPage";
import { EnvironmentGuide } from "../components/access/AccessAdministration";
import type { AccessCatalog } from "../lib/rootAccess";
import { fetchAccess, mutateAccess } from "../lib/rootAccess";
vi.mock("../lib/supabase", () => ({
  supabase: { auth: { getSession: async () => ({ data: { session: null } }) } },
}));
vi.mock("../lib/rootAccess", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/rootAccess")>()),
  fetchAccess: vi.fn(),
  mutateAccess: vi.fn(),
}));
vi.mock("../lib/folderQueries", () => ({
  breadcrumbOptions: () => ({
    queryKey: ["breadcrumbs"],
    queryFn: async () => [
      { id: "11111111-1111-4111-8111-111111111111", name: "Cosm" },
    ],
  }),
}));
const root = "11111111-1111-4111-8111-111111111111";
const catalog: AccessCatalog = {
  root_id: root,
  guide: {
    markdown: "# Cosm\n\n<script>alert('bad')</script>\n\nUse `MONGO_URI`.",
    revision: 3,
  },
  environments: [
    { id: "env", name: "Staging", slug: "staging", sensitivity: "normal" },
  ],
  resources: [
    {
      id: "res",
      name: "SES MongoDB",
      description: "Tracking storage",
      type: "database",
      aliases: ["homologação"],
      shared: false,
      account: "",
      region: "",
    },
  ],
  bindings: [
    {
      id: "binding",
      resource_id: "res",
      environment_id: "env",
      consumer: "ses",
      field_mapping: { MONGO_URI: "connection" },
      clear_env: [],
      revision: 4,
      enabled: true,
      has_secret: true,
      credential_expires_at: null,
    },
  ],
  devices: [
    {
      id: "device",
      label: "MacBook",
      created_at: "2026-11-14",
      last_used_at: null,
      expires_at: "2026-12-14",
      revoked_at: null,
    },
  ],
  grants: [],
  activity: [],
  provider: { configured: true },
};
function render() {
  return renderWithProviders(
    <Routes>
      <Route path="/folders/:rootId/access" element={<RootAccessPage />} />
    </Routes>,
    { initialEntries: [`/folders/${root}/access`] },
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchAccess).mockResolvedValue(structuredClone(catalog));
  vi.mocked(mutateAccess).mockResolvedValue({ ok: true });
});
describe("root access interface", () => {
  it("searches aliases and keeps resource selection scoped to current binding", async () => {
    render();
    await screen.findByRole("button", { name: "Configure SES MongoDB" });
    fireEvent.change(screen.getByLabelText("Search resources"), {
      target: { value: "homologação" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Configure SES MongoDB" }),
    );
    expect(
      await screen.findByText("Stored in central vault"),
    ).toBeInTheDocument();
    expect(screen.getByText("MONGO_URI")).toBeInTheDocument();
  });
  it("writes credentials through the dedicated endpoint and clears on provider failure", async () => {
    vi.mocked(mutateAccess).mockRejectedValue(
      new Error("provider password: DO-NOT-PRINT"),
    );
    render();
    fireEvent.click(
      await screen.findByRole("button", { name: "Configure SES MongoDB" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Replace" }));
    const input = screen.getByLabelText(/Secret field: connection/);
    expect(input).toHaveAttribute("type", "password");
    fireEvent.change(input, { target: { value: "SYNTHETIC-CANARY" } });
    fireEvent.click(screen.getByRole("button", { name: "Save credential" }));
    await waitFor(() =>
      expect(mutateAccess).toHaveBeenCalledWith(
        root,
        "/bindings/binding/credential",
        "POST",
        expect.objectContaining({
          expected_revision: 4,
          values: { connection: "SYNTHETIC-CANARY" },
        }),
      ),
    );
    await screen.findByText("Could not complete this request. Try again.");
    expect(input).toHaveValue("");
    expect(document.body.textContent).not.toContain("DO-NOT-PRINT");
  });
  it("renders safe Markdown and saves its original revision", async () => {
    render();
    await screen.findByRole("button", { name: "Configure SES MongoDB" });
    fireEvent.click(screen.getByRole("tab", { name: "Environment guide" }));
    expect(document.querySelector(".access-preview script")).toBeNull();
    fireEvent.change(screen.getByLabelText("Markdown guide"), {
      target: { value: "# Updated" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save guide" }));
    await waitFor(() =>
      expect(mutateAccess).toHaveBeenCalledWith(root, "/guide", "PUT", {
        markdown: "# Updated",
        expected_revision: 3,
      }),
    );
  });
  it("requires explicit confirmation before revoking a computer", async () => {
    render();
    await screen.findByRole("button", { name: "Configure SES MongoDB" });
    fireEvent.click(screen.getByRole("tab", { name: "Computers & access" }));
    fireEvent.click(screen.getByRole("button", { name: "Revoke computer" }));
    expect(mutateAccess).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Revoke access" }));
    await waitFor(() =>
      expect(mutateAccess).toHaveBeenCalledWith(
        root,
        "/devices/device/revoke",
        "POST",
        {},
      ),
    );
  });
});

describe("guide concurrent edits", () => {
  it("keeps the draft and original revision when server metadata refreshes", async () => {
    const view = renderWithProviders(
      <EnvironmentGuide root={root} catalog={catalog} onSaved={() => {}} />,
    );
    fireEvent.change(screen.getByLabelText("Markdown guide"), {
      target: { value: "My unsaved work" },
    });
    view.rerender(
      <EnvironmentGuide
        root={root}
        catalog={{
          ...catalog,
          guide: { markdown: "External edit", revision: 4 },
        }}
        onSaved={() => {}}
      />,
    );
    expect(screen.getByLabelText("Markdown guide")).toHaveValue(
      "My unsaved work",
    );
    fireEvent.click(screen.getByRole("button", { name: "Save guide" }));
    await waitFor(() =>
      expect(mutateAccess).toHaveBeenCalledWith(root, "/guide", "PUT", {
        markdown: "My unsaved work",
        expected_revision: 3,
      }),
    );
  });
});
