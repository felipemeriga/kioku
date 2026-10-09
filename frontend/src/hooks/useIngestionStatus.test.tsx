import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useIngestionStatus } from "./useIngestionStatus";

vi.mock("../lib/api", () => ({
  uploadDocument: vi
    .fn()
    .mockResolvedValue({ task_id: "t1", duplicate: false }),
  // Server reports the uploaded doc as still in-flight.
  fetchIngestionStatus: vi
    .fn()
    .mockResolvedValue([{ id: "t1", filename: "a.md", stage: "parsing" }]),
}));

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe("useIngestionStatus (React Query)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("is idle until the first upload", () => {
    const { result } = renderHook(() => useIngestionStatus(), { wrapper });
    expect(result.current.drawerOpen).toBe(false);
    expect(result.current.tasks).toEqual([]);
  });

  it("opens the drawer and surfaces the in-flight task on upload", async () => {
    const { result } = renderHook(() => useIngestionStatus(), { wrapper });

    await act(async () => {
      await result.current.upload(new File(["x"], "a.md"));
    });

    // Drawer opens immediately on upload.
    expect(result.current.drawerOpen).toBe(true);

    // The query (now enabled + refetched) surfaces the active task.
    await waitFor(() => expect(result.current.hasActiveTasks).toBe(true));
    expect(result.current.tasks.some((t) => t.id === "t1")).toBe(true);
  });
});
