import { useEffect, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Stack,
  Typography,
} from "@mui/material";
import { useAuth } from "../hooks/useAuth";
import {
  deviceInfo,
  deviceComplete,
  deviceDeny,
  type DeviceInfo,
} from "../lib/api";
import { brand, fonts } from "../theme";

type UiState =
  | "loading"
  | "confirm"
  | "invalid"
  | "authorized"
  | "denied"
  | "error";

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
    return (
      <Navigate
        to={`/login?redirect=${encodeURIComponent(`/cli-auth?req=${req}`)}`}
        replace
      />
    );
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
    <Box
      component="main"
      data-testid="cli-auth-page"
      sx={{
        minHeight: "100dvh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        p: "70px 20px",
        bgcolor: brand.ink,
      }}
    >
      <Box
        component="article"
        sx={{
          width: "100%",
          maxWidth: 510,
          p: "34px",
          border: `1px solid ${brand.line}`,
          borderRadius: "8px",
          bgcolor: brand.surface,
          "@media(max-width:480px)": { p: "26px 22px" },
        }}
      >
        <Stack
          direction="row"
          spacing="13px"
          alignItems="center"
          sx={{ mb: "36px" }}
        >
          <Box
            aria-hidden="true"
            sx={{
              width: 38,
              height: 42,
              display: "grid",
              placeItems: "center",
              border: `1px solid ${brand.magenta}`,
              color: brand.magenta,
              borderRadius: "3px",
              fontFamily: fonts.jp,
              fontSize: 25,
            }}
          >
            記
          </Box>
          <Typography
            sx={{ fontSize: 23, fontWeight: 600, letterSpacing: "-.8px" }}
          >
            kioku
          </Typography>
        </Stack>
        {state === "loading" && (
          <Box
            role="status"
            sx={{ display: "flex", alignItems: "center", gap: 2 }}
          >
            <CircularProgress size={24} sx={{ color: brand.cyan }} />
            <Typography sx={{ color: brand.muted }}>
              Checking this login request…
            </Typography>
          </Box>
        )}
        {state === "invalid" && (
          <Alert severity="error">
            {info?.expired
              ? "This login link has expired. Run `kioku login` again."
              : "Invalid login link. Run `kioku login` again."}
          </Alert>
        )}
        {state === "error" && (
          <Alert severity="error">
            Something went wrong. Run `kioku login` again.
          </Alert>
        )}
        {state === "authorized" && (
          <Alert severity="success">
            You're signed in. Return to your terminal.
          </Alert>
        )}
        {state === "denied" && <Alert severity="info">Login denied.</Alert>}
        {state === "confirm" && info && (
          <>
            <Typography
              component="h1"
              sx={{
                fontSize: 28,
                lineHeight: 1.3,
                fontWeight: 600,
                mb: "16px",
                "@media(max-width:480px)": { fontSize: 25 },
              }}
            >
              Sign in to the Kioku CLI?
            </Typography>
            <Typography
              sx={{ fontSize: 16, lineHeight: 1.7, color: brand.muted }}
            >
              A terminal on{" "}
              <Box
                component="strong"
                sx={{ color: brand.text, fontWeight: 600 }}
              >
                {info.hostname}
              </Box>{" "}
              is requesting access to your Kioku account.
            </Typography>
            <Box
              component="dl"
              sx={{
                m: "24px 0",
                p: "16px 18px",
                bgcolor: brand.ink,
                border: `1px solid ${brand.line}`,
                borderRadius: "5px",
                "& > div": {
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "baseline",
                  gap: 2,
                  py: "6px",
                  fontSize: 13,
                },
                "& dt": { color: brand.muted },
                "& dd": {
                  m: 0,
                  textAlign: "right",
                  fontWeight: 500,
                  overflowWrap: "anywhere",
                },
              }}
            >
              <Box>
                <dt>Account</dt>
                <dd>{session?.user.email ?? "Signed-in account"}</dd>
              </Box>
              <Box>
                <dt>Operating system</dt>
                <dd>{info.os || "Not reported"}</dd>
              </Box>
            </Box>
            <Typography
              sx={{ fontSize: 14, color: brand.muted, lineHeight: 1.7 }}
            >
              Only approve this if you just ran{" "}
              <Box
                component="code"
                sx={{ fontFamily: fonts.mono, color: brand.text }}
              >
                kioku login
              </Box>{" "}
              on that machine.
            </Typography>
            <Stack direction="row" spacing="12px" sx={{ mt: "28px" }}>
              <Button
                variant="contained"
                onClick={authorize}
                disabled={busy}
                sx={{ minHeight: 44, flex: 1 }}
              >
                {busy ? "Authorizing…" : "Authorize CLI"}
              </Button>
              <Button
                variant="outlined"
                onClick={refuse}
                disabled={busy}
                sx={{ minHeight: 44 }}
              >
                Deny
              </Button>
            </Stack>
          </>
        )}
      </Box>
    </Box>
  );
}
