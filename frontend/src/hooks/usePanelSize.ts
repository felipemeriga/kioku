import { useCallback, useEffect, useState } from "react";

const prefix = "kioku:panels:v1:";
export function readPanelSize(
  key: string,
  fallback: number,
  min: number,
  max: number,
) {
  try {
    const raw = localStorage.getItem(prefix + key);
    if (raw === null) return fallback;
    const value: unknown = JSON.parse(raw);
    return typeof value === "number" && Number.isFinite(value)
      ? Math.round(Math.max(min, Math.min(max, value)))
      : fallback;
  } catch {
    return fallback;
  }
}
export function savePanelPreference(key: string, value: number | boolean) {
  try {
    localStorage.setItem(prefix + key, JSON.stringify(value));
  } catch {
    // Browsers with blocked/full storage still support the current layout.
  }
}
export function readNavigationCollapsed() {
  try {
    return localStorage.getItem(prefix + "navigationCollapsed") === "true";
  } catch {
    return false;
  }
}
export function usePanelSize(
  key: string,
  initial: number,
  min: number,
  max: number,
  reserved = 0,
) {
  const [desired, setDesired] = useState(() =>
    readPanelSize(key, initial, min, max),
  );
  const [viewport, setViewport] = useState(() => window.innerWidth);
  useEffect(() => {
    const update = () => setViewport(window.innerWidth);
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  const limit = Math.max(min, Math.min(max, viewport - reserved));
  const setSize = useCallback(
    (value: number) => {
      if (!Number.isFinite(value)) return;
      const next = Math.round(Math.max(min, Math.min(max, value)));
      setDesired(next);
      savePanelPreference(key, next);
    },
    [key, min, max],
  );
  return { size: Math.min(desired, limit), setSize, min, max: limit, initial };
}
