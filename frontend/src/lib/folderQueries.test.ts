import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it, vi } from "vitest";
import {
  breadcrumbOptions,
  documentOptions,
  folderOptions,
  prefetchFolder,
} from "./folderQueries";
import { fetchBreadcrumbs, fetchDocuments, fetchFolders } from "./api";

vi.mock("./api", () => ({
  fetchBreadcrumbs: vi.fn(async () => []),
  fetchDocuments: vi.fn(async () => []),
  fetchFolders: vi.fn(async () => []),
}));

describe("folder navigation cache", () => {
  it("shares intent-prefetched data with the page, but isolates other folders", async () => {
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    prefetchFolder(client, "a");
    await Promise.all([
      client.fetchQuery(folderOptions("a")),
      client.fetchQuery(documentOptions("a")),
      client.fetchQuery(breadcrumbOptions("a")),
    ]);
    expect(fetchFolders).toHaveBeenCalledTimes(1);
    expect(fetchDocuments).toHaveBeenCalledTimes(1);
    expect(fetchBreadcrumbs).toHaveBeenCalledTimes(1);
    expect(client.getQueryData(documentOptions("b").queryKey)).toBeUndefined();
    await client.invalidateQueries({ queryKey: documentOptions("a").queryKey });
    await client.fetchQuery(documentOptions("a"));
    expect(fetchDocuments).toHaveBeenCalledTimes(2);
    client.clear();
  });
});
