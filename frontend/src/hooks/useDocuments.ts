import { useCallback } from "react";
import {
  useQuery,
  useMutation,
  useQueryClient,
  keepPreviousData,
} from "@tanstack/react-query";
import type { DocumentInfo } from "../lib/api";
import {
  fetchDocuments,
  deleteDocument as apiDelete,
  moveDocument as apiMove,
} from "../lib/api";
import { qk } from "../lib/queryKeys";
import { messageFromError } from "../components/ToastProvider";

export function useDocuments(folderId?: string | null) {
  const queryClient = useQueryClient();
  const normId = folderId ?? null;

  const query = useQuery({
    queryKey: qk.documents(normId),
    queryFn: () => fetchDocuments(folderId),
    // Keep the previous folder's documents on screen while the new folder
    // loads, so switching folders never flashes an empty grid.
    placeholderData: keepPreviousData,
  });

  const documents: DocumentInfo[] = query.data ?? [];
  // Only the very first (cold) load has no data — folder switches show the
  // previous folder's list via placeholderData, so no skeleton flashes.
  const loading = query.isPending;
  const error = query.isError
    ? `Couldn't load documents: ${messageFromError(query.error)}`
    : null;

  const loadDocuments = useCallback(async () => {
    await queryClient.invalidateQueries({ queryKey: qk.documents(normId) });
  }, [queryClient, normId]);

  const moveMut = useMutation({
    mutationFn: ({
      filename,
      targetFolderId,
    }: {
      filename: string;
      targetFolderId: string | null;
    }) => apiMove(filename, targetFolderId),
    onSuccess: (_data, { targetFolderId }) => {
      queryClient.invalidateQueries({ queryKey: qk.documents(normId) });
      queryClient.invalidateQueries({ queryKey: qk.documents(targetFolderId) });
    },
  });

  const removeMut = useMutation({
    mutationFn: (filename: string) => apiDelete(filename),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: qk.documents(normId) }),
  });

  // Keep the original call signatures; both reject on failure so callers
  // (MoveDialog, delete confirm) can toast and keep their dialog open.
  const move = useCallback(
    (filename: string, targetFolderId: string | null) =>
      moveMut.mutateAsync({ filename, targetFolderId }),
    [moveMut]
  );

  const remove = useCallback(
    (filename: string) => removeMut.mutateAsync(filename),
    [removeMut]
  );

  return { documents, loading, error, loadDocuments, move, remove };
}
