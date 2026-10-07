import { useState, useEffect, useCallback } from "react";
import type { DocumentInfo } from "../lib/api";
import {
  fetchDocuments,
  deleteDocument as apiDelete,
  moveDocument as apiMove,
} from "../lib/api";
import { getCached, setCached, clearCached } from "../lib/folderCache";
import { messageFromError } from "../components/ToastProvider";

const key = (folderId?: string | null) => `docs:${folderId ?? "root"}`;

export function useDocuments(folderId?: string | null) {
  const cacheKey = key(folderId);
  const [documents, setDocuments] = useState<DocumentInfo[]>(
    () => getCached<DocumentInfo[]>(cacheKey) ?? []
  );
  // Cold load = no cached data yet for this folder. Used by the page to show a
  // skeleton instead of a blank grid; a revisit (cache hit) never shows it.
  const [loading, setLoading] = useState(
    () => getCached<DocumentInfo[]>(cacheKey) === undefined
  );
  const [error, setError] = useState<string | null>(null);

  // Adjust state during render when the folder changes, so we never paint a
  // frame of the *previous* folder's documents before the effect runs. This is
  // React's recommended "derive state from props" pattern.
  const [renderedKey, setRenderedKey] = useState(cacheKey);
  if (renderedKey !== cacheKey) {
    setRenderedKey(cacheKey);
    const cached = getCached<DocumentInfo[]>(cacheKey);
    setDocuments(cached ?? []);
    setLoading(cached === undefined);
    setError(null);
  }

  const loadDocuments = useCallback(async () => {
    try {
      setError(null);
      const docs = await fetchDocuments(folderId);
      setCached(cacheKey, docs);
      setDocuments(docs);
      setLoading(false);
    } catch (err) {
      setError(`Couldn't load documents: ${messageFromError(err)}`);
      setLoading(false);
    }
  }, [folderId, cacheKey]);

  // Revalidate on folder change (stale-while-revalidate). The `active` flag
  // drops a stale response when the user switches folders mid-flight, so an
  // earlier folder's result can't overwrite the current one.
  useEffect(() => {
    let active = true;
    fetchDocuments(folderId)
      .then((docs) => {
        if (!active) return;
        setCached(cacheKey, docs);
        setDocuments(docs);
        setLoading(false);
      })
      .catch((err) => {
        if (!active) return;
        setError(`Couldn't load documents: ${messageFromError(err)}`);
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [folderId, cacheKey]);

  const move = useCallback(
    async (filename: string, targetFolderId: string | null) => {
      try {
        setError(null);
        await apiMove(filename, targetFolderId);
        setDocuments((prev) => {
          const next = prev.filter((d) => d.source_filename !== filename);
          setCached(cacheKey, next);
          return next;
        });
        // The file now lives in another folder — drop that folder's stale cache
        // so its next visit refetches and shows the moved file.
        clearCached(key(targetFolderId));
      } catch (err) {
        setError(`Couldn't move “${filename}”: ${messageFromError(err)}`);
        // Re-throw so callers (e.g. MoveDialog) can toast + keep dialog open.
        throw err;
      }
    },
    [cacheKey]
  );

  const remove = useCallback(
    async (filename: string) => {
      try {
        setError(null);
        await apiDelete(filename);
        setDocuments((prev) => {
          const next = prev.filter((d) => d.source_filename !== filename);
          setCached(cacheKey, next);
          return next;
        });
      } catch (err) {
        setError(`Couldn't delete “${filename}”: ${messageFromError(err)}`);
        throw err;
      }
    },
    [cacheKey]
  );

  return {
    documents,
    loading,
    error,
    loadDocuments,
    move,
    remove,
  };
}
