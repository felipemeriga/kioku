import { useState, useEffect, useCallback } from "react";
import type { DocumentInfo } from "../lib/api";
import {
  fetchDocuments,
  deleteDocument as apiDelete,
  moveDocument as apiMove,
} from "../lib/api";
import { messageFromError } from "../components/ToastProvider";

export function useDocuments(folderId?: string | null) {
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadDocuments = useCallback(async () => {
    try {
      setError(null);
      const docs = await fetchDocuments(folderId);
      setDocuments(docs);
    } catch (err) {
      setError(`Couldn't load documents: ${messageFromError(err)}`);
    }
  }, [folderId]);

  // Initial-load effect — mirrors loadDocuments but tolerates unmount.
  // Errors surface via the same `error` state so the page-level Alert renders.
  useEffect(() => {
    let active = true;
    fetchDocuments(folderId)
      .then((docs) => {
        if (active) setDocuments(docs);
      })
      .catch((err) => {
        if (active) setError(`Couldn't load documents: ${messageFromError(err)}`);
      });
    return () => {
      active = false;
    };
  }, [folderId]);

  const move = useCallback(
    async (filename: string, targetFolderId: string | null) => {
      try {
        setError(null);
        await apiMove(filename, targetFolderId);
        setDocuments((prev) =>
          prev.filter((d) => d.source_filename !== filename)
        );
      } catch (err) {
        setError(`Couldn't move “${filename}”: ${messageFromError(err)}`);
        // Re-throw so callers (e.g. MoveDialog) can toast + keep dialog open.
        throw err;
      }
    },
    []
  );

  const remove = useCallback(async (filename: string) => {
    try {
      setError(null);
      await apiDelete(filename);
      setDocuments((prev) =>
        prev.filter((d) => d.source_filename !== filename)
      );
    } catch (err) {
      setError(`Couldn't delete “${filename}”: ${messageFromError(err)}`);
      throw err;
    }
  }, []);

  return {
    documents,
    error,
    loadDocuments,
    move,
    remove,
  };
}
