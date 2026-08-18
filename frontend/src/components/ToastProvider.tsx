import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";
import { Alert, IconButton, Snackbar, Stack } from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import { ApiError } from "../lib/api";

type Severity = "error" | "warning" | "info" | "success";

interface Toast {
  id: number;
  message: string;
  severity: Severity;
  actionLabel?: string;
  onAction?: () => void;
}

interface ToastAPI {
  show: (msg: string, severity?: Severity, opts?: Partial<Toast>) => void;
  showError: (err: unknown, fallback?: string) => void;
  showSuccess: (msg: string) => void;
}

const ToastContext = createContext<ToastAPI | null>(null);

// eslint-disable-next-line react-refresh/only-export-components
export function useToast(): ToastAPI {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside <ToastProvider>");
  return ctx;
}

/**
 * Convert any thrown value into a user-friendly message. ApiError already
 * carries a good one; anything else gets a best-effort extraction.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function messageFromError(err: unknown, fallback = "Something went wrong."): string {
  if (err instanceof ApiError) return err.userMessage;
  if (err instanceof Error) return err.message || fallback;
  if (typeof err === "string") return err;
  return fallback;
}

export default function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const idRef = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const show = useCallback<ToastAPI["show"]>((message, severity = "info", opts) => {
    idRef.current += 1;
    const id = idRef.current;
    setToasts((prev) => [
      ...prev,
      { id, message, severity, actionLabel: opts?.actionLabel, onAction: opts?.onAction },
    ]);
  }, []);

  const api = useMemo<ToastAPI>(
    () => ({
      show,
      showError: (err, fallback) => show(messageFromError(err, fallback), "error"),
      showSuccess: (msg) => show(msg, "success"),
    }),
    [show],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <Stack
        spacing={1}
        sx={{
          position: "fixed",
          bottom: 24,
          right: 24,
          zIndex: (t) => t.zIndex.snackbar,
          maxWidth: 480,
        }}
      >
        {toasts.map((t) => (
          <Snackbar
            key={t.id}
            open
            autoHideDuration={t.severity === "error" ? 8000 : 4000}
            onClose={(_, reason) => {
              if (reason !== "clickaway") dismiss(t.id);
            }}
            sx={{ position: "static", transform: "none" }}
          >
            <Alert
              severity={t.severity}
              variant="filled"
              sx={{
                width: "100%",
                boxShadow: 3,
                "& .MuiAlert-message": { flex: 1 },
              }}
              action={
                <>
                  {t.actionLabel && t.onAction && (
                    <IconButton
                      size="small"
                      color="inherit"
                      onClick={() => {
                        t.onAction?.();
                        dismiss(t.id);
                      }}
                      sx={{ fontSize: "0.85rem", fontWeight: 600, px: 1 }}
                    >
                      {t.actionLabel}
                    </IconButton>
                  )}
                  <IconButton
                    size="small"
                    color="inherit"
                    onClick={() => dismiss(t.id)}
                    aria-label="dismiss"
                  >
                    <CloseIcon fontSize="small" />
                  </IconButton>
                </>
              }
            >
              {t.message}
            </Alert>
          </Snackbar>
        ))}
      </Stack>
    </ToastContext.Provider>
  );
}
