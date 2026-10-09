import { useState, useEffect, useCallback, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchIngestionStatus, uploadDocument } from "../lib/api";
import type { IngestionTask } from "../lib/api";
import { qk } from "../lib/queryKeys";

const TERMINAL_STAGES = new Set(["completed", "error", "duplicate"]);
const POLL_INTERVAL = 2000;
const AUTO_CLOSE_DELAY = 10000;

const isActive = (t: IngestionTask) => !TERMINAL_STAGES.has(t.stage);

export function useIngestionStatus() {
  const queryClient = useQueryClient();
  const [drawerOpen, setDrawerOpen] = useState(false);
  // Stays idle until the first upload this session (matches the old behavior
  // where `tasks` started empty and nothing polled until you uploaded).
  const [started, setStarted] = useState(false);
  const autoCloseTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const interactedRef = useRef(false);

  const { data: tasks = [] } = useQuery({
    queryKey: qk.ingestionStatus(),
    queryFn: fetchIngestionStatus,
    enabled: started,
    // A 401 is handled globally (apiFetch signs the user out) — don't retry.
    retry: false,
    // Poll every 2s while any task is still in-flight; stop once all terminal.
    refetchInterval: (query) =>
      ((query.state.data ?? []) as IngestionTask[]).some(isActive)
        ? POLL_INTERVAL
        : false,
    // Don't resurrect finished/cleared tasks when the window regains focus.
    refetchOnWindowFocus: false,
  });

  const activeTasks = tasks.filter(isActive);
  const hasActiveTasks = activeTasks.length > 0;

  // Auto-close the drawer ~10s after everything finishes (unless the user
  // interacted). setState runs inside the timer callback, not the effect body.
  useEffect(() => {
    if (autoCloseTimer.current) {
      clearTimeout(autoCloseTimer.current);
      autoCloseTimer.current = null;
    }
    if (tasks.length > 0 && !hasActiveTasks && drawerOpen) {
      interactedRef.current = false;
      autoCloseTimer.current = setTimeout(() => {
        if (!interactedRef.current) {
          setDrawerOpen(false);
          queryClient.setQueryData(qk.ingestionStatus(), []);
        }
      }, AUTO_CLOSE_DELAY);
    }
    return () => {
      if (autoCloseTimer.current) clearTimeout(autoCloseTimer.current);
    };
  }, [tasks, hasActiveTasks, drawerOpen, queryClient]);

  const cancelAutoClose = useCallback(() => {
    interactedRef.current = true;
    if (autoCloseTimer.current) {
      clearTimeout(autoCloseTimer.current);
      autoCloseTimer.current = null;
    }
  }, []);

  const upload = useCallback(
    async (file: File, folderId?: string | null) => {
      const result = await uploadDocument(file, folderId);
      const placeholder: IngestionTask = {
        id: result.task_id,
        user_id: "",
        filename: file.name,
        folder_id: folderId ?? null,
        stage: "uploading",
        stage_detail: "Starting...",
        error_message: null,
        chunks_total: null,
        chunks_done: 0,
        duplicate: false,
        document_ids: [],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      };
      // Optimistic placeholder for instant feedback; mark started so the query
      // runs, then refetch server truth (which also kicks off the poll loop).
      queryClient.setQueryData<IngestionTask[]>(
        qk.ingestionStatus(),
        (prev) => [...(prev ?? []), placeholder]
      );
      setStarted(true);
      setDrawerOpen(true);
      cancelAutoClose();
      void queryClient.invalidateQueries({ queryKey: qk.ingestionStatus() });
    },
    [queryClient, cancelAutoClose]
  );

  const closeDrawer = useCallback(() => {
    setDrawerOpen(false);
    if (!hasActiveTasks) {
      queryClient.setQueryData(qk.ingestionStatus(), []);
    }
  }, [hasActiveTasks, queryClient]);

  const openDrawer = useCallback(() => {
    setDrawerOpen(true);
    cancelAutoClose();
  }, [cancelAutoClose]);

  return {
    tasks,
    activeTasks,
    hasActiveTasks,
    drawerOpen,
    upload,
    openDrawer,
    closeDrawer,
    cancelAutoClose,
  };
}
