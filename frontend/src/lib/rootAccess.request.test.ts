import { renderHook } from "@testing-library/react";
import { useAccessRequests } from "../hooks/useAccessRequests";
import { beforeEach, afterEach, describe, it, expect, vi } from "vitest";
import {
  fetchAccess,
  mutateAccess,
  accessError,
  AccessTimeoutError,
} from "./rootAccess";
const { getSession } = vi.hoisted(() => ({ getSession: vi.fn() }));
vi.mock("./supabase", () => ({ supabase: { auth: { getSession } } }));
beforeEach(() => {
  vi.useFakeTimers();
  getSession.mockResolvedValue({ data: { session: { access_token: "test" } } });
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
const never = () => new Promise(() => {});
describe("access request deadlines", () => {
  it("bounds never-settling auth before any HTTP request", async () => {
    getSession.mockImplementation(never);
    const pending = fetchAccess("root").catch((e) => e);
    await vi.advanceTimersByTimeAsync(15000);
    const error = await pending;
    expect(error).toBeInstanceOf(AccessTimeoutError);
    expect(fetch).not.toHaveBeenCalled();
    expect(accessError(error)).toMatch(/too long/);
  });
  it("aborts a never-settling network request", async () => {
    vi.mocked(fetch).mockImplementation(never as typeof fetch);
    const pending = fetchAccess("root").catch((e) => e);
    await vi.advanceTimersByTimeAsync(15000);
    expect(await pending).toBeInstanceOf(AccessTimeoutError);
    expect(vi.mocked(fetch).mock.calls[0][1]?.signal?.aborted).toBe(true);
  });
  it("includes response JSON in the total deadline", async () => {
    vi.mocked(fetch).mockResolvedValue({
      ok: true,
      status: 200,
      json: never,
    } as unknown as Response);
    const pending = fetchAccess("root").catch((e) => e);
    await vi.advanceTimersByTimeAsync(15000);
    expect(await pending).toBeInstanceOf(AccessTimeoutError);
  });
  it("cancels active reads with the query signal", async () => {
    vi.mocked(fetch).mockImplementation(never as typeof fetch);
    const controller = new AbortController();
    const pending = fetchAccess("root", controller.signal).catch((e) => e);
    await vi.advanceTimersByTimeAsync(1);
    controller.abort();
    expect(await pending).toMatchObject({ name: "AbortError" });
    expect(vi.mocked(fetch).mock.calls[0][1]?.signal?.aborted).toBe(true);
  });
  it("does not retry a timed out write or echo its payload", async () => {
    vi.mocked(fetch).mockImplementation(never as typeof fetch);
    const pending = mutateAccess("root", "/bindings/b/credential", "POST", {
      values: { connection: "SYNTHETIC-CANARY" },
    }).catch((e) => e);
    await vi.advanceTimersByTimeAsync(15000);
    const error = await pending;
    expect(error).toBeInstanceOf(AccessTimeoutError);
    expect(accessError(error)).toMatch(/pending/);
    expect(accessError(error)).not.toContain("SYNTHETIC-CANARY");
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(30000);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});

describe("access screen cancellation", () => {
  it("aborts mutations when their owning screen unmounts", async () => {
    vi.mocked(fetch).mockImplementation(never as typeof fetch);
    const view = renderHook(() => useAccessRequests("root"));
    const pending = view.result
      .current("/guide", "PUT", { markdown: "test", expected_revision: 1 })
      .catch((e) => e);
    await vi.advanceTimersByTimeAsync(1);
    view.unmount();
    expect(await pending).toMatchObject({ name: "AbortError" });
    expect(vi.mocked(fetch).mock.calls[0][1]?.signal?.aborted).toBe(true);
  });
});
