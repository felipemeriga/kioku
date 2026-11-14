import { describe, expect, it, vi } from "vitest";
import {
  mappingError,
  parseMapping,
  resourceError,
  accessError,
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
