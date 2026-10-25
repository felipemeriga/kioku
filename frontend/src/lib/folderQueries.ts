import type { QueryClient } from "@tanstack/react-query";
import { fetchBreadcrumbs, fetchDocuments, fetchFolders } from "./api";
import { qk } from "./queryKeys";

export const FOLDER_STALE_TIME = 60_000;
export const folderOptions = (id: string | null) => ({
  queryKey: qk.folders(id),
  queryFn: () => fetchFolders(id),
  staleTime: FOLDER_STALE_TIME,
});
export const documentOptions = (id: string | null) => ({
  queryKey: qk.documents(id),
  queryFn: () => fetchDocuments(id),
  staleTime: FOLDER_STALE_TIME,
});
export const breadcrumbOptions = (id: string) => ({
  queryKey: qk.breadcrumbs(id),
  queryFn: () => fetchBreadcrumbs(id),
  staleTime: FOLDER_STALE_TIME,
});

/** Start only the folder the user points to; matching keys deduplicate tree/page reads. */
export function prefetchFolder(client: QueryClient, id: string | null): void {
  void client.prefetchQuery(folderOptions(id));
  void client.prefetchQuery(documentOptions(id));
  if (id) void client.prefetchQuery(breadcrumbOptions(id));
}
