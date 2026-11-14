import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import { renderWithProviders } from "../test/renderWithProviders";
import RootAccessPage from "./RootAccessPage";
import { ApiError } from "../lib/api";
import { useAuth } from "../hooks/useAuth";
import { EnvironmentGuide } from "../components/access/AccessAdministration";
import type { AccessCatalog } from "../lib/rootAccess";
import {
  fetchAccess,
  mutateAccess,
  AccessTimeoutError,
} from "../lib/rootAccess";
vi.mock("../hooks/useAuth", () => ({
  useAuth: vi.fn(() => ({ user: { id: "owner" }, loading: false })),
}));
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
      pending_operation_id: null,
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
  vi.mocked(useAuth).mockReturnValue({
    user: { id: "owner" },
    loading: false,
  } as ReturnType<typeof useAuth>);
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
        expect.any(AbortSignal),
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
      expect(mutateAccess).toHaveBeenCalledWith(
        root,
        "/guide",
        "PUT",
        {
          markdown: "# Updated",
          expected_revision: 3,
        },
        expect.any(AbortSignal),
      ),
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
        expect.any(AbortSignal),
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
      expect(mutateAccess).toHaveBeenCalledWith(
        root,
        "/guide",
        "PUT",
        {
          markdown: "My unsaved work",
          expected_revision: 3,
        },
        expect.any(AbortSignal),
      ),
    );
  });
});

describe("account isolation", () => {
  it("hides prior metadata and disables access requests while auth is changing", async () => {
    const view = render();
    await screen.findByRole("button", { name: "Configure SES MongoDB" });
    const requests = vi.mocked(fetchAccess).mock.calls.length;
    vi.mocked(useAuth).mockReturnValue({
      user: null,
      loading: true,
    } as ReturnType<typeof useAuth>);
    view.rerender(
      <Routes>
        <Route path="/folders/:rootId/access" element={<RootAccessPage />} />
      </Routes>,
    );
    expect(
      screen.queryByRole("button", { name: "Configure SES MongoDB" }),
    ).not.toBeInTheDocument();
    expect(fetchAccess).toHaveBeenCalledTimes(requests);
  });
});

describe("pending credential recovery", () => {
  it.each(["unavailable", "timeout"])(
    "recovers a %s write without retaining or resending plaintext",
    async (failure) => {
      const current = structuredClone(catalog);
      vi.mocked(fetchAccess).mockImplementation(async () =>
        structuredClone(current),
      );
      vi.mocked(mutateAccess).mockImplementation(async (_root, path) => {
        if (path.endsWith("/reconcile")) {
          current.bindings[0].pending_operation_id = null;
          current.bindings[0].revision = 5;
          return { ok: true, state: "completed", revision: 5 };
        }
        current.bindings[0].pending_operation_id = "write-id";
        if (failure === "timeout") throw new AccessTimeoutError(true);
        throw new ApiError({
          status: 503,
          userMessage: "unsafe provider diagnostic",
        });
      });
      render();
      fireEvent.click(
        await screen.findByRole("button", { name: "Configure SES MongoDB" }),
      );
      fireEvent.click(screen.getByRole("button", { name: "Replace" }));
      fireEvent.change(screen.getByLabelText(/Secret field: connection/), {
        target: { value: "RECOVERY-CANARY" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Save credential" }));
      const recovery = await screen.findByRole("button", {
        name: "Reconcile pending write",
      });
      if (failure === "timeout")
        expect(
          await screen.findByText(/Its outcome may be pending/),
        ).toBeInTheDocument();
      expect(screen.getByLabelText(/Secret field: connection/)).toHaveValue("");
      expect(
        screen.getByRole("button", { name: "Save credential" }),
      ).toBeDisabled();
      fireEvent.click(recovery);
      await waitFor(() =>
        expect(mutateAccess).toHaveBeenCalledWith(
          root,
          "/bindings/binding/credential/reconcile",
          "POST",
          {},
          expect.any(AbortSignal),
        ),
      );
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Replace" })).toBeEnabled(),
      );
      expect(
        screen.queryByRole("button", { name: "Reconcile pending write" }),
      ).not.toBeInTheDocument();
      expect(document.body.textContent).not.toContain("RECOVERY-CANARY");
    },
  );
});
