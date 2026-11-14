import { useCallback, useEffect, useRef } from "react";
import { mutateAccess } from "../lib/rootAccess";

/** Cancels this screen's requests on unmount or root change, including StrictMode replays. */
export function useAccessRequests(root: string) {
  const controller = useRef<AbortController | null>(null);
  useEffect(() => {
    const active = new AbortController();
    controller.current = active;
    return () => active.abort();
  }, [root]);
  return useCallback(
    <T = unknown>(suffix: string, method: string, body?: unknown) =>
      mutateAccess<T>(root, suffix, method, body, controller.current?.signal),
    [root],
  );
}
