import { describe, expect, it, vi } from "vitest";
import {
  mappingError,
  parseMapping,
  resourceError,
  accessError,
  allowedVariable,
  allowedClearVariable,
  accessKey,
} from "./rootAccess";

vi.mock("./supabase", () => ({
  supabase: { auth: { getSession: async () => ({ data: { session: null } }) } },
}));

describe("access validation", () => {
  it("rejects loader variables, invalid names and duplicate mappings", () => {
    expect(mappingError("MONGO_URI=connection\nMONGO_URI=other")).toMatch(
      /once/,
    );
    expect(mappingError("LD_PRELOAD=value")).toMatch(/allowed/);
    expect(mappingError("bad-name=value")).toMatch(/allowed/);
    expect(
      parseMapping("MONGO_URI=connection\nMONGODB_URL=connection"),
    ).toEqual({ MONGO_URI: "connection", MONGODB_URL: "connection" });
  });
  it("validates resource metadata and alias bounds", () => {
    expect(resourceError("", [])).toMatch(/name/);
    expect(resourceError("SES", Array(21).fill("alias"))).toMatch(/20/);
  });
  it("never displays provider errors or secret values", () => {
    expect(accessError(new Error("mongodb://secret-value"))).not.toContain(
      "secret-value",
    );
  });
});

describe("runtime selector safety", () => {
  it.each([
    "PATH",
    "HOME",
    "USERPROFILE",
    "COMSPEC",
    "SYSTEMROOT",
    "SystemRoot",
    "PATHEXT",
    "IFS",
    "CDPATH",
    "ZDOTDIR",
    "PYTHONSTARTUP",
    "LD_PRELOAD",
    "DYLD_INSERT_LIBRARIES",
    "AWS_PROFILE",
    "AWS_CONFIG_FILE",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_EC2_METADATA_DISABLED",
  ])("blocks %s as an injected variable", (name) =>
    expect(allowedVariable(name)).toBe(false),
  );
  it("permits clearing SDK selectors but never core process variables", () => {
    expect(allowedClearVariable("AWS_PROFILE")).toBe(true);
    expect(allowedClearVariable("LD_PRELOAD")).toBe(true);
    expect(allowedClearVariable("PATH")).toBe(false);
  });
  it("requires the AWS credential pair for cloud mappings", () => {
    expect(mappingError("AWS_ACCESS_KEY_ID=key", "cloud")).toMatch(/both/);
    expect(
      mappingError(
        "AWS_ACCESS_KEY_ID=key\nAWS_SECRET_ACCESS_KEY=secret",
        "cloud",
      ),
    ).toBe("");
  });
  it("isolates query keys by account", () =>
    expect(accessKey("root", "owner-a")).not.toEqual(
      accessKey("root", "owner-b"),
    ));
});
