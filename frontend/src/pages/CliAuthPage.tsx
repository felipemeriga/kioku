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
import CornerCard from "../components/neo/CornerCard";
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
      sx={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        p: 2,
        background: brand.ink,
        backgroundImage: `
          radial-gradient(circle at 20% 0%, ${brand.magenta}26 0%, transparent 45%),
          radial-gradient(circle at 90% 100%, ${brand.cyan}18 0%, transparent 45%),
          repeating-linear-gradient(0deg, rgba(255,255,255,0.018) 0px, rgba(255,255,255,0.018) 1px, transparent 1px, transparent 3px)
        `,
      }}
    >
      <CornerCard
        corners={4}
        color={brand.magenta}
        sx={{
          width: 480,
          maxWidth: "100%",
          display: "flex",
          flexDirection: "column",
          gap: "18px",
          p: "32px",
        }}
      >
        {state === "loading" && (
          <CircularProgress sx={{ color: brand.magenta }} />
        )}
        {state === "invalid" && (
          <Alert severity="error">
            Invalid login link. Run `kioku login` again.
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
              sx={{ m: 0, fontSize: 24, fontWeight: 700, color: brand.text }}
            >
              Sign in to the Kioku CLI?
            </Typography>

            <Typography
              sx={{ m: 0, fontSize: 16, lineHeight: 1.6, color: brand.muted }}
            >
              A CLI on{" "}
              <Box
                component="span"
                sx={{
                  px: "6px",
                  py: "1px",
                  borderRadius: "3px",
                  background: `${brand.cyan}14`,
                  border: `1px solid ${brand.cyan}55`,
                  fontFamily: fonts.mono,
                  fontSize: 14,
                  color: brand.cyan,
                }}
              >
                {info.hostname}
              </Box>{" "}
              <Box
                component="span"
                sx={{
                  fontFamily: fonts.mono,
                  fontSize: 14,
                  color: brand.muted,
                }}
              >
                ({info.os})
              </Box>{" "}
              is requesting access to your account.
            </Typography>

            <Stack direction="row" spacing="10px">
              <Button
                onClick={authorize}
                disabled={busy}
                sx={{
                  height: 44,
                  px: "22px",
                  border: 0,
                  borderRadius: "4px",
                  backgroundImage: `linear-gradient(90deg, ${brand.magentaDeep} 0%, ${brand.purple} 100%)`,
                  color: "#fff",
                  fontWeight: 700,
                  fontSize: 15,
                  textTransform: "none",
                  boxShadow: `0 4px 12px ${brand.magenta}44`,
                  "&:hover": {
                    backgroundImage: `linear-gradient(90deg, ${brand.magenta} 0%, ${brand.purple} 100%)`,
                    boxShadow: `0 4px 16px ${brand.magenta}66`,
                  },
                  "&.Mui-disabled": { opacity: 0.5 },
                }}
              >
                Authorize
              </Button>
              <Button
                onClick={refuse}
                disabled={busy}
                sx={{
                  height: 44,
                  px: "18px",
                  borderRadius: "4px",
                  border: `1px solid ${brand.lineGlow}`,
                  background: "transparent",
                  color: brand.text,
                  fontWeight: 600,
                  fontSize: 15,
                  textTransform: "none",
                  "&:hover": {
                    borderColor: brand.magenta,
                    background: "transparent",
                  },
                  "&.Mui-disabled": { opacity: 0.5 },
                }}
              >
                Deny
              </Button>
            </Stack>
          </>
        )}
      </CornerCard>
    </Box>
  );
}
