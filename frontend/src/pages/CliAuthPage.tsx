import { useEffect, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { Alert, Box, Button, CircularProgress, Stack, Typography } from "@mui/material";
import { useAuth } from "../hooks/useAuth";
import { deviceInfo, deviceComplete, deviceDeny, type DeviceInfo } from "../lib/api";

type UiState = "loading" | "confirm" | "invalid" | "authorized" | "denied" | "error";

export default function CliAuthPage() {
  const [params] = useSearchParams();
  const req = params.get("req");
  const { session, loading: authLoading } = useAuth();
  const [state, setState] = useState<UiState>("loading");
  const [info, setInfo] = useState<DeviceInfo | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!req) {
      setState("invalid");
      return;
    }
    if (authLoading || !session) return; // wait for redirect-to-login below
    deviceInfo(req)
      .then((i) => {
        setInfo(i);
        setState(i.valid ? "confirm" : "invalid");
      })
      .catch(() => setState("error"));
  // Use !!session (not session) to avoid re-running when the session object
  // reference changes on re-renders (e.g. after setBusy flips state).
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [req, !!session, authLoading]);

  if (!authLoading && !session && req) {
    return <Navigate to={`/login?redirect=${encodeURIComponent(`/cli-auth?req=${req}`)}`} replace />;
  }

  const authorize = async () => {
    if (!req) return;
    setBusy(true);
    try {
      await deviceComplete(req);
      setState("authorized");
    } catch {
      setState("error");
    } finally {
      setBusy(false);
    }
  };
  const refuse = async () => {
    if (!req) return;
    setBusy(true);
    try {
      await deviceDeny(req);
    } catch {
      /* best effort */
    } finally {
      setBusy(false);
      setState("denied");
    }
  };

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", alignItems: "center", justifyContent: "center", p: 2 }}>
      <Stack spacing={2} sx={{ maxWidth: 420, width: "100%" }}>
        {state === "loading" && <CircularProgress />}
        {state === "invalid" && <Alert severity="error">Invalid login link. Run `kioku login` again.</Alert>}
        {state === "error" && <Alert severity="error">Something went wrong. Run `kioku login` again.</Alert>}
        {state === "authorized" && <Alert severity="success">You're signed in. Return to your terminal.</Alert>}
        {state === "denied" && <Alert severity="info">Login denied.</Alert>}
        {state === "confirm" && info && (
          <>
            <Typography variant="h6">Sign in to the Kioku CLI?</Typography>
            <Typography color="text.secondary">
              A CLI on <strong>{info.hostname}</strong> ({info.os}) is requesting access to your account.
            </Typography>
            <Stack direction="row" spacing={1.5}>
              <Button variant="contained" onClick={authorize} disabled={busy}>Authorize</Button>
              <Button variant="outlined" onClick={refuse} disabled={busy}>Deny</Button>
            </Stack>
          </>
        )}
      </Stack>
    </Box>
  );
}
