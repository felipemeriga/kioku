import { useState, useEffect, useCallback, useRef } from "react";
import { fetchIngestionStatus, uploadDocument } from "../lib/api";
import type { IngestionTask } from "../lib/api";

const TERMINAL_STAGES = new Set(["completed", "error", "duplicate"]);
const POLL_INTERVAL = 2000;
const AUTO_CLOSE_DELAY = 10000;

export function useIngestionStatus() {
  const [tasks, setTasks] = useState<IngestionTask[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const autoCloseTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const interactedRef = useRef(false);

  const activeTasks = tasks.filter((t) => !TERMINAL_STAGES.has(t.stage));
  const hasActiveTasks = activeTasks.length > 0;

  // Poll for status updates
  useEffect(() => {
    if (tasks.length === 0) return;

    const poll = async () => {
      try {
        const updated = await fetchIngestionStatus();
        setTasks(updated);
      } catch {
        // Silently ignore poll errors
      }
    };

    // Only poll if there are active tasks
    if (!hasActiveTasks) return;

    const interval = setInterval(poll, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [tasks.length, hasActiveTasks]);

  // Auto-close drawer when all tasks finish
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
          // Clean up finished tasks after close
          setTasks([]);
        }
      }, AUTO_CLOSE_DELAY);
    }

    return () => {
      if (autoCloseTimer.current) {
        clearTimeout(autoCloseTimer.current);
      }
    };
  }, [tasks, hasActiveTasks, drawerOpen]);

  const cancelAutoClose = useCallback(() => {
    interactedRef.current = true;
    if (autoCloseTimer.current) {
      clearTimeout(autoCloseTimer.current);
      autoCloseTimer.current = null;
    }
  }, []);

  // Upload throws on failure so the caller can toast; on success, inserts the
  // placeholder task and opens the drawer. Previously an unhandled promise
  // rejection would leave the user with no signal that the upload failed.
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
      setTasks((prev) => [...prev, placeholder]);
      setDrawerOpen(true);
      cancelAutoClose();
      try {
        const updated = await fetchIngestionStatus();
        setTasks(updated);
      } catch {
        // Non-fatal: placeholder stands in until the next poll.
      }
    },
    [cancelAutoClose]
  );

  const closeDrawer = useCallback(() => {
    setDrawerOpen(false);
    if (!hasActiveTasks) {
      setTasks([]);
    }
  }, [hasActiveTasks]);

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
