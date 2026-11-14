import { describe, it, expect, vi } from "vitest";
import { usageError, usageFields, usageCapabilities } from "./accessUsage";
import type { AccessCredential, UsageDelivery } from "./rootAccess";
vi.mock("./supabase", () => ({ supabase: {} }));
const c: AccessCredential = {
  id: "c",
  resource_id: "r",
  environment_id: null,
  label: "",
  kind: "fields",
  fields: ["connection", "token"],
  enabled: true,
  revision: 1,
  has_secret: true,
  credential_expires_at: null,
  pending_operation_id: null,
  fingerprint: null,
  legacy_binding_id: null,
};
describe("usage recipes", () => {
  it("maps multiple fields and rejects unknown fields", () => {
    const d: UsageDelivery = {
      kind: "env",
      field_mapping: { DB_URI: "connection", API_TOKEN: "token" },
      clear_env: [],
    };
    expect(usageFields(d)).toEqual(["connection", "token"]);
    expect(usageError(d, c)).toBe("");
    expect(usageError({ ...d, field_mapping: { DB: "missing" } }, c)).toMatch(
      /fields/
    );
  });
  it("rejects runtime injection variables", () => {
    expect(
      usageError(
        {
          kind: "env",
          field_mapping: { NODE_OPTIONS: "connection" },
          clear_env: [],
        },
        c
      )
    ).toMatch(/allowed/);
  });
  it("requires raw argv acknowledgement and capability", () => {
    const d: UsageDelivery = {
      kind: "argv",
      arguments: [
        { kind: "literal", value: "--token" },
        { kind: "field", field: "token" },
      ],
      allow_raw_secret_argv: false,
    };
    expect(usageError(d, c)).toMatch(/process lists/);
    expect(usageCapabilities(d)).toEqual(["argv", "raw_secret_argv"]);
  });
  it("rejects path traversal and invalid JSON templates", () => {
    const d: UsageDelivery = {
      kind: "file",
      format: "json",
      source_template: "{}",
      patches: [{ path: ["..", "db"], field: "connection" }],
      destination: { kind: "arg", name: "--config" },
    };
    expect(usageError(d, c)).toMatch(/unsafe/);
    expect(usageError({ ...d, source_template: "broken" }, c)).toMatch(/JSON/);
  });
  it("requires pinned SSH host key", () => {
    const d: UsageDelivery = {
      kind: "ssh",
      host: "example.com",
      user: "runner",
      port: 22,
      host_key: "",
      private_key_field: "connection",
      passphrase_field: null,
    };
    expect(usageError(d, c)).toMatch(/Pin/);
  });
  it("AWS requires pair and disallows raw flags", () => {
    const aws = {
      ...c,
      kind: "aws" as const,
      fields: ["access_key_id", "secret_access_key", "session_token"],
    };
    expect(
      usageError(
        {
          kind: "env",
          field_mapping: { AWS_ACCESS_KEY_ID: "access_key_id" },
          clear_env: [],
        },
        aws
      )
    ).toMatch(/both/);
    expect(
      usageError(
        {
          kind: "argv",
          arguments: [{ kind: "field", field: "access_key_id" }],
          allow_raw_secret_argv: true,
        },
        aws
      )
    ).toMatch(/AWS/);
    expect(
      usageError(
        {
          kind: "env",
          field_mapping: {
            AWS_ACCESS_KEY_ID: "access_key_id",
            AWS_SECRET_ACCESS_KEY: "secret_access_key",
            AWS_SESSION_TOKEN: "session_token",
          },
          clear_env: [],
        },
        aws
      )
    ).toBe("");
  });
});
