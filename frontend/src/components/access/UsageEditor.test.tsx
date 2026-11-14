import { beforeEach, describe, it, expect, vi } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithProviders } from "../../test/renderWithProviders";
import UsageEditor from "./UsageEditor";
import { mutateAccess } from "../../lib/rootAccess";
import type { AccessCredential } from "../../lib/rootAccess";
vi.mock("../../lib/supabase", () => ({ supabase: {} }));
vi.mock("../../lib/rootAccess", async (original) => ({
  ...(await original<typeof import("../../lib/rootAccess")>()),
  mutateAccess: vi.fn(),
}));
const c: AccessCredential = {
  id: "aws",
  resource_id: "r",
  environment_id: "e",
  label: "",
  kind: "aws",
  fields: ["access_key_id", "secret_access_key", "session_token"],
  revision: 1,
  enabled: true,
  has_secret: true,
  credential_expires_at: null,
  pending_operation_id: null,
  fingerprint: null,
  legacy_binding_id: null,
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(mutateAccess).mockResolvedValue({});
});
function setup() {
  renderWithProviders(
    <UsageEditor
      root="root"
      credential={c}
      onSaved={() => {}}
      onBack={() => {}}
    />
  );
  fireEvent.change(screen.getByLabelText(/Recipe name/), {
    target: { value: "AWS CLI" },
  });
  fireEvent.change(screen.getByLabelText(/Application or repository/), {
    target: { value: "platform" },
  });
}
describe("AWS usage forms", () => {
  it("saves the whole credential bundle in one environment recipe", async () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Save recipe" }));
    await waitFor(() =>
      expect(mutateAccess).toHaveBeenCalledWith(
        "root",
        "/usages",
        "POST",
        expect.objectContaining({
          delivery: {
            kind: "env",
            field_mapping: {
              AWS_ACCESS_KEY_ID: "access_key_id",
              AWS_SECRET_ACCESS_KEY: "secret_access_key",
              AWS_SESSION_TOKEN: "session_token",
            },
            clear_env: [],
          },
        }),
        expect.any(AbortSignal)
      )
    );
  });
  it("presets a protected AWS profile file rather than inventing raw key CLI flags", async () => {
    setup();
    fireEvent.mouseDown(screen.getByLabelText("Delivery method"));
    fireEvent.click(
      await screen.findByRole("option", {
        name: "Temporary configuration file",
      })
    );
    expect(screen.getByLabelText("Nonsecret source template")).toHaveValue(
      "[default]\n"
    );
    expect(screen.getByLabelText("Destination name")).toHaveValue(
      "AWS_SHARED_CREDENTIALS_FILE"
    );
    expect(screen.getByLabelText("Destination name")).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Save recipe" }));
    await waitFor(() =>
      expect(mutateAccess).toHaveBeenCalledWith(
        "root",
        "/usages",
        "POST",
        expect.objectContaining({
          delivery: {
            kind: "file",
            format: "toml",
            source_template: "[default]\n",
            patches: [
              {
                path: ["default", "aws_access_key_id"],
                field: "access_key_id",
              },
              {
                path: ["default", "aws_secret_access_key"],
                field: "secret_access_key",
              },
              {
                path: ["default", "aws_session_token"],
                field: "session_token",
              },
            ],
            destination: { kind: "env", name: "AWS_SHARED_CREDENTIALS_FILE" },
          },
        }),
        expect.any(AbortSignal)
      )
    );
  });
});
