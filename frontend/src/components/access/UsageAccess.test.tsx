import { beforeEach, describe, it, expect, vi } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithProviders } from "../../test/renderWithProviders";
import UsageAccess from "./UsageAccess";
import { mutateAccess } from "../../lib/rootAccess";
import type { AccessCatalog, AccessUsage } from "../../lib/rootAccess";
vi.mock("../../lib/supabase", () => ({ supabase: {} }));
vi.mock("../../lib/rootAccess", async (original) => ({
  ...(await original<typeof import("../../lib/rootAccess")>()),
  mutateAccess: vi.fn(),
}));
const usage: AccessUsage = {
  id: "u",
  credential_id: "c",
  name: "CLI",
  consumer: "tests",
  delivery: {
    kind: "env",
    field_mapping: { SYNTHETIC_TOKEN: "token" },
    clear_env: [],
  },
  revision: 1,
  enabled: true,
  legacy_binding_id: null,
};
const catalog: AccessCatalog = {
  root_id: "r",
  guide: { markdown: "", revision: 0 },
  environments: [],
  resources: [],
  bindings: [],
  credentials: [],
  usages: [usage],
  usage_grants: [],
  devices: [
    {
      id: "d",
      label: "Test machine",
      created_at: "2026-11-14",
      last_used_at: null,
      expires_at: "2035-01-01",
      revoked_at: null,
    },
  ],
  grants: [],
  activity: [],
  provider: { configured: true },
};
const props = {
  root: "r",
  catalog,
  usages: [usage],
  credentials: [],
  onSaved: () => {},
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(mutateAccess).mockResolvedValue({});
});
async function select() {
  fireEvent.mouseDown(screen.getByLabelText(/^Computer/));
  fireEvent.click(await screen.findByRole("option", { name: "Test machine" }));
  fireEvent.mouseDown(screen.getByLabelText(/^Usage recipe/));
  fireEvent.click(await screen.findByRole("option", { name: "CLI · tests" }));
  fireEvent.click(screen.getByRole("checkbox"));
}
describe("reviewed usage access", () => {
  it("sends the exact reviewed recipe revision and shows destination mapping", async () => {
    renderWithProviders(<UsageAccess {...props} />);
    await select();
    expect(
      screen.getByText(/SYNTHETIC_TOKEN ← credential.token/)
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Grant access" }));
    await waitFor(() =>
      expect(mutateAccess).toHaveBeenCalledWith(
        "r",
        "/usage-grants",
        "POST",
        expect.objectContaining({
          expected_usage_revision: 1,
          usage_id: "u",
          device_id: "d",
          allowed_fields: ["token"],
          capabilities: ["env"],
        }),
        expect.any(AbortSignal)
      )
    );
  });
  it("invalidates acknowledgement when metadata refresh changes recipe revision", async () => {
    const view = renderWithProviders(<UsageAccess {...props} />);
    await select();
    expect(screen.getByRole("button", { name: "Grant access" })).toBeEnabled();
    view.rerender(
      <UsageAccess {...props} usages={[{ ...usage, revision: 2 }]} />
    );
    expect(screen.getByRole("checkbox")).not.toBeChecked();
    expect(screen.getByRole("button", { name: "Grant access" })).toBeDisabled();
    expect(mutateAccess).not.toHaveBeenCalled();
  });
});
