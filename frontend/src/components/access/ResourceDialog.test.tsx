import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { renderWithProviders } from "../../test/renderWithProviders";
import ResourceDialog from "./ResourceDialog";
import type { AccessCatalog, AccessCredential } from "../../lib/rootAccess";
import { mutateAccess } from "../../lib/rootAccess";
vi.mock("../../lib/supabase", () => ({ supabase: {} }));
vi.mock("../../lib/rootAccess", async (original) => ({
  ...(await original<typeof import("../../lib/rootAccess")>()),
  mutateAccess: vi.fn(),
}));
const credential: AccessCredential = {
  id: "cred",
  resource_id: "resource",
  environment_id: "staging",
  label: "",
  kind: "uri",
  fields: ["connection"],
  revision: 1,
  enabled: true,
  has_secret: false,
  credential_expires_at: null,
  pending_operation_id: null,
  fingerprint: null,
  legacy_binding_id: null,
};
const catalog: AccessCatalog = {
  root_id: "root",
  guide: { markdown: "", revision: 0 },
  environments: [
    { id: "staging", name: "Staging", slug: "staging", sensitivity: "normal" },
  ],
  resources: [
    {
      id: "resource",
      name: "SES MongoDB",
      description: "Tracking",
      type: "database",
      aliases: [],
      shared: false,
      account: "",
      region: "",
      environment_ids: ["staging"],
      credential_kind: "uri",
      credential_fields: ["connection"],
    },
  ],
  bindings: [],
  credentials: [],
  usages: [],
  usage_grants: [],
  devices: [],
  grants: [],
  activity: [],
  provider: { configured: true },
};
const onSaved = vi.fn();
function render(c = structuredClone(catalog)) {
  return renderWithProviders(
    <ResourceDialog
      root="root"
      catalog={c}
      resource={c.resources[0]}
      onClose={() => {}}
      onSaved={onSaved}
    />
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(mutateAccess).mockResolvedValue(credential);
});
describe("resource-first credentials", () => {
  it("adds an environment credential without a consumer or variable mapping", async () => {
    render();
    fireEvent.click(screen.getByRole("button", { name: "Add credential" }));
    await screen.findByLabelText(/connection/i);
    expect(mutateAccess).toHaveBeenCalledWith(
      "root",
      "/credentials",
      "POST",
      expect.objectContaining({
        environment_id: "staging",
        fields: ["connection"],
      }),
      expect.any(AbortSignal)
    );
    expect(screen.queryByLabelText("Application or crate")).toBeNull();
  });
  it("clears values on failed writes and never displays provider errors", async () => {
    const c = structuredClone(catalog);
    c.credentials = [credential];
    render(c);
    fireEvent.click(screen.getByRole("button", { name: "Add credential" }));
    const input = screen.getByLabelText(/connection/i);
    fireEvent.change(input, { target: { value: "SECRET-CANARY" } });
    vi.mocked(mutateAccess).mockRejectedValueOnce(
      new Error("provider SECRET-CANARY")
    );
    fireEvent.click(screen.getByRole("button", { name: "Save credential" }));
    await screen.findByText("Could not complete this request. Try again.");
    expect(input).toHaveValue("");
    expect(
      screen.getByRole("button", { name: "Save credential" })
    ).toBeDisabled();
    expect(document.body.textContent).not.toContain("SECRET-CANARY");
  });
  it("uses one shared credential row without account or region prerequisite", () => {
    const c = structuredClone(catalog);
    c.resources[0].shared = true;
    c.resources[0].environment_ids = [];
    render(c);
    expect(screen.getByText("Shared")).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "Add credential" })
    ).toHaveLength(1);
  });
  it("keeps duplicate legacy variants distinct", () => {
    const c = structuredClone(catalog);
    c.credentials = [
      { ...credential, id: "one", legacy_binding_id: "old-one", label: "ses" },
      {
        ...credential,
        id: "two",
        legacy_binding_id: "old-two",
        label: "business",
      },
    ];
    render(c);
    expect(screen.getByText("Legacy variant · ses")).toBeInTheDocument();
    expect(screen.getByText("Legacy variant · business")).toBeInTheDocument();
  });
  it("renders every independent credential variant in one environment", () => {
    const c = structuredClone(catalog);
    c.credentials = [
      { ...credential, id: "first", label: "Account one" },
      { ...credential, id: "second", label: "Account two" },
    ];
    render(c);
    expect(screen.getByText("Variant · Account one")).toBeInTheDocument();
    expect(screen.getByText("Variant · Account two")).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: /Add credential/ })
    ).toHaveLength(2);
  });
  it("rejects invalid AWS bundle whitespace without sending a write", () => {
    const c = structuredClone(catalog);
    c.credentials = [
      {
        ...credential,
        kind: "aws",
        fields: ["access_key_id", "secret_access_key"],
      },
    ];
    render(c);
    fireEvent.click(screen.getByRole("button", { name: "Add credential" }));
    fireEvent.change(screen.getByLabelText(/access key id/i), {
      target: { value: "invalid key" },
    });
    fireEvent.change(screen.getByLabelText(/secret access key/i), {
      target: { value: "SYNTHETIC" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save credential" }));
    expect(
      screen.getByText(
        "AWS credential fields cannot contain whitespace or control characters."
      )
    ).toBeInTheDocument();
    expect(mutateAccess).not.toHaveBeenCalled();
  });
  it("uses AWS region metadata CAS before writing bundle at new revision", async () => {
    const c = structuredClone(catalog);
    c.credentials = [
      {
        ...credential,
        kind: "aws",
        fields: ["access_key_id", "secret_access_key", "session_token"],
        region: "",
      },
    ];
    render(c);
    fireEvent.click(screen.getByRole("button", { name: "Add credential" }));
    fireEvent.change(screen.getByLabelText(/access key id/i), {
      target: { value: "SYNTHETIC_ID" },
    });
    fireEvent.change(screen.getByLabelText(/secret access key/i), {
      target: { value: "SYNTHETIC_KEY" },
    });
    fireEvent.change(screen.getByLabelText(/Region \(non-secret/), {
      target: { value: "us-east-1" },
    });
    vi.mocked(mutateAccess).mockResolvedValueOnce({
      ...c.credentials[0],
      revision: 2,
    });
    fireEvent.click(screen.getByRole("button", { name: "Save credential" }));
    await waitFor(() =>
      expect(mutateAccess).toHaveBeenCalledWith(
        "root",
        "/credentials/cred/value",
        "POST",
        expect.objectContaining({
          expected_revision: 2,
          values: {
            access_key_id: "SYNTHETIC_ID",
            secret_access_key: "SYNTHETIC_KEY",
          },
        }),
        expect.any(AbortSignal)
      )
    );
    expect(mutateAccess).toHaveBeenNthCalledWith(
      1,
      "root",
      "/credentials/cred",
      "PATCH",
      { expected_revision: 1, region: "us-east-1" },
      expect.any(AbortSignal)
    );
  });
});
