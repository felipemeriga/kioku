import { useState, type FormEvent } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { safeRedirect } from "../lib/redirect";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Link as MuiLink,
  Stack,
  TextField,
  Typography,
  alpha,
} from "@mui/material";
import { supabase } from "../lib/supabase";
import { useAuth } from "../hooks/useAuth";
import { brand, fonts, scanlines } from "../theme";
import GridFloor from "../components/neo/GridFloor";
import KatakanaAccent from "../components/neo/KatakanaAccent";
import CornerCard from "../components/neo/CornerCard";
import RetroSun from "../components/neo/RetroSun";

export default function LoginPage() {
  const { session, loading: authLoading } = useAuth();
  const [isSignUp, setIsSignUp] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const [params] = useSearchParams();
  const dest = safeRedirect(params.get("redirect"));
  if (!authLoading && session) {
    return <Navigate to={dest} replace />;
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const { error: authError } = isSignUp
        ? await supabase.auth.signUp({
            email,
            password,
            // Send the confirmation link back to the app it was requested
            // from (https://kioku.merigafy.com in prod, localhost in dev)
            // instead of relying solely on the project's Site URL. Must be
            // allow-listed under Supabase Auth → URL Configuration.
            options: { emailRedirectTo: window.location.origin },
          })
        : await supabase.auth.signInWithPassword({ email, password });
      if (authError) {
        // Common cases: 400 Invalid login credentials, 422 email format, 429 rate limit
        setError(authError.message);
      }
    } catch (err) {
      // TypeError from fetch: DNS/CORS/network — Supabase throws bare Errors here,
      // so we catch and translate to something the user can act on.
      setError(
        err instanceof Error && err.message
          ? `${err.message} — check your internet connection.`
          : "Couldn't reach the sign-in service. Check your internet connection."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        position: "relative",
        overflow: "hidden",
        // Hard horizon split at 62% — sky above, dark below
        background: `linear-gradient(180deg, #08040F 0%, #1A0630 62%, #08040F 62.1%)`,
        px: 2,
      }}
    >
      {/* Retrowave sun — centered above the horizon (38% from bottom = 62% from top) */}
      <RetroSun
        sx={{
          left: "50%",
          transform: "translateX(-50%)",
          // Position so the flat base aligns ~at the 62% horizon line.
          // Sun is 260px tall; horizon at 62% means top of sun = 62vh - 260px.
          bottom: "38%",
          zIndex: 0,
        }}
      />

      {/* Grid floor perspective — below horizon */}
      <GridFloor animate sx={{ zIndex: 0 }} />

      {/* Magenta horizon line — sits exactly at the 62% horizon */}
      <Box
        aria-hidden="true"
        sx={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: "38%",
          height: "3px",
          background: brand.magenta,
          boxShadow: `0 0 18px ${brand.magenta}`,
          pointerEvents: "none",
          zIndex: 1,
        }}
      />

      {/* CRT scanlines overlay */}
      <Box
        aria-hidden="true"
        sx={{
          position: "absolute",
          inset: 0,
          backgroundImage: scanlines,
          pointerEvents: "none",
          zIndex: 1,
        }}
      />

      {/* Vertical kanji accent — left side, bright neon per mockup */}
      <KatakanaAccent
        text="記憶"
        sx={{
          left: 80,
          top: 120,
          fontSize: 96,
          writingMode: "vertical-rl",
          color: "#FFE3F1",
          WebkitTextStroke: "unset",
          textShadow: `0 0 2px ${brand.magenta}, 0 0 10px ${brand.magenta}, 0 0 28px ${brand.magenta}, 0 0 56px ${brand.magenta}99`,
          opacity: 0.9,
          zIndex: 2,
        }}
      />

      {/* Main content column */}
      <Stack
        spacing={2.25}
        alignItems="center"
        sx={{ position: "relative", width: "100%", maxWidth: 420, zIndex: 2 }}
      >
        {/* AI pill */}
        <Box
          sx={{
            px: 1.75,
            py: 0.75,
            border: `1px solid ${alpha(brand.cyan, 0.4)}`,
            borderRadius: 999,
            bgcolor: alpha(brand.cyan, 0.06),
            boxShadow: `0 0 12px ${alpha(brand.cyan, 0.2)}`,
            display: "flex",
            alignItems: "center",
            gap: 1,
          }}
        >
          <Box
            component="span"
            sx={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              bgcolor: brand.cyan,
              boxShadow: `0 0 6px ${brand.cyan}`,
              flexShrink: 0,
            }}
          />
          <Typography
            sx={{
              fontFamily: fonts.mono,
              fontSize: "0.68rem",
              letterSpacing: "0.3em",
              color: brand.cyan,
              lineHeight: 1,
            }}
          >
            AI · PERSONAL KNOWLEDGE AGENT
          </Typography>
        </Box>

        {/* Logo row: kanji box + wordmark */}
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <Box
            sx={{
              width: 48,
              height: 48,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              border: `1.5px solid ${brand.magenta}`,
              borderRadius: 1,
              bgcolor: brand.ink,
              boxShadow: `0 0 4px ${alpha(
                brand.magenta,
                0.53
              )}, 0 0 16px ${alpha(brand.magenta, 0.27)}`,
              fontFamily: fonts.jp,
              fontWeight: 900,
              fontSize: "1.65rem",
              color: brand.magentaGlow,
              textShadow: `0 0 8px ${brand.magenta}, 0 0 16px ${alpha(
                brand.magenta,
                0.67
              )}`,
            }}
          >
            記
          </Box>
          <Stack spacing={0.2} sx={{ lineHeight: 1 }}>
            <Typography
              sx={{
                fontFamily: fonts.dot,
                fontSize: "0.72rem",
                letterSpacing: "0.4em",
                color: brand.cyan,
                lineHeight: 1,
              }}
            >
              キオク
            </Typography>
            <Typography
              sx={{
                fontFamily: fonts.display,
                fontSize: "1.875rem",
                fontWeight: 700,
                lineHeight: 1.1,
                textShadow: `0 0 14px ${alpha(brand.magenta, 0.4)}`,
              }}
            >
              Kioku
            </Typography>
          </Stack>
        </Stack>

        {/* Auth card */}
        <CornerCard
          component="form"
          onSubmit={handleSubmit}
          corners={4}
          color={brand.cyan}
          sx={{
            width: "100%",
            p: 3.5,
            bgcolor: `${brand.surface}f2`,
            boxShadow: "0 12px 32px rgba(0,0,0,0.55)",
            display: "flex",
            flexDirection: "column",
            gap: 1.75,
          }}
        >
          {/* Heading */}
          <Box>
            <Typography
              sx={{
                fontFamily: fonts.display,
                fontWeight: 700,
                fontSize: "1.375rem",
                color: brand.text,
                mb: 0.5,
              }}
            >
              {isSignUp ? "Create your account" : "Welcome back"}
            </Typography>
            <Typography
              sx={{
                fontFamily: fonts.body,
                fontSize: "0.875rem",
                color: brand.muted,
              }}
            >
              {isSignUp
                ? "Sign up to start building your second brain."
                : "Sign in to your second brain."}
            </Typography>
          </Box>

          {/* Email field */}
          <TextField
            label="Email"
            type="email"
            fullWidth
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            InputLabelProps={{
              required: false,
              sx: {
                fontFamily: fonts.mono,
                fontSize: "0.68rem",
                letterSpacing: "0.22em",
                textTransform: "uppercase",
                color: brand.muted,
              },
            }}
            autoComplete="email"
          />

          {/* Password field */}
          <TextField
            label="Password"
            type="password"
            fullWidth
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            InputLabelProps={{
              required: false,
              sx: {
                fontFamily: fonts.mono,
                fontSize: "0.68rem",
                letterSpacing: "0.22em",
                textTransform: "uppercase",
                color: brand.muted,
              },
            }}
            autoComplete={isSignUp ? "new-password" : "current-password"}
          />

          {error && <Alert severity="error">{error}</Alert>}

          {/* Sign in / Sign up button */}
          <Button
            type="submit"
            variant="contained"
            fullWidth
            disabled={loading}
            sx={{
              py: 1.375,
              mt: 0.5,
              backgroundImage: `linear-gradient(90deg, ${brand.magentaDeep} 0%, ${brand.purple} 100%)`,
              boxShadow: `0 4px 12px ${alpha(brand.magenta, 0.27)}`,
              "&:hover": {
                backgroundImage: `linear-gradient(90deg, ${brand.magenta} 0%, ${brand.purple} 100%)`,
                boxShadow: `0 6px 20px ${alpha(brand.magenta, 0.4)}`,
              },
            }}
          >
            {loading ? (
              <CircularProgress size={22} color="inherit" />
            ) : isSignUp ? (
              "Sign up"
            ) : (
              "Sign in"
            )}
          </Button>

          {/* OR divider */}
          <Stack direction="row" alignItems="center" spacing={1.25}>
            <Box sx={{ flex: 1, height: 1, bgcolor: brand.line }} />
            <Typography
              sx={{
                fontFamily: fonts.mono,
                fontSize: "0.68rem",
                letterSpacing: "0.3em",
                color: brand.muted,
              }}
            >
              OR
            </Typography>
            <Box sx={{ flex: 1, height: 1, bgcolor: brand.line }} />
          </Stack>

          {/* Sign up / Sign in toggle */}
          <Typography
            sx={{
              fontFamily: fonts.body,
              fontSize: "0.875rem",
              color: brand.muted,
              textAlign: "center",
            }}
          >
            {isSignUp ? "Already have an account? " : "Need an account? "}
            <MuiLink
              component="button"
              type="button"
              onClick={() => {
                setIsSignUp(!isSignUp);
                setError("");
              }}
              sx={{
                color: brand.violet2,
                fontFamily: fonts.display,
                fontWeight: 600,
                textDecoration: "none",
                "&:hover": { textDecoration: "underline" },
              }}
            >
              {isSignUp ? "Sign in" : "Sign up"}
            </MuiLink>
          </Typography>
        </CornerCard>

        {/* Footer tagline */}
        <Typography
          sx={{
            fontFamily: fonts.mono,
            fontSize: "0.65rem",
            letterSpacing: "0.3em",
            color: brand.muted,
            mt: 0.5,
          }}
        >
          FEED IT{" "}
          <Box
            component="span"
            sx={{
              color: brand.amber,
              textShadow: `0 0 8px ${alpha(brand.amber, 0.53)}`,
            }}
          >
            EVERYTHING
          </Box>
          {" · ASK "}
          <Box
            component="span"
            sx={{
              color: brand.cyan,
              textShadow: `0 0 8px ${alpha(brand.cyan, 0.53)}`,
            }}
          >
            ANYTHING
          </Box>
        </Typography>
      </Stack>
    </Box>
  );
}
