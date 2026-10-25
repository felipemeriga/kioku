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
} from "@mui/material";
import { supabase } from "../lib/supabase";
import { useAuth } from "../hooks/useAuth";
import { brand, fonts, neonGlow } from "../theme";
import NeoAtmosphere from "../components/neo/NeoAtmosphere";

export default function LoginPage() {
  const { session, loading: authLoading } = useAuth();
  const [isSignUp, setIsSignUp] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);

  const [params] = useSearchParams();
  const dest = safeRedirect(params.get("redirect"));
  if (!authLoading && session) {
    return <Navigate to={dest} replace />;
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setNotice("");
    setLoading(true);
    try {
      if (isSignUp) {
        const { data, error: authError } = await supabase.auth.signUp({
          email,
          password,
          // Send the confirmation link back to the app it was requested
          // from (https://kioku.merigafy.com in prod, localhost in dev)
          // instead of relying solely on the project's Site URL. Must be
          // allow-listed under Supabase Auth → URL Configuration.
          options: { emailRedirectTo: window.location.origin },
        });
        if (authError) {
          setError(authError.message);
        } else if (!data.session) {
          // Email confirmation is required → no session yet. Tell the user to
          // go confirm (otherwise the screen just sat there with no feedback).
          setNotice(
            `Almost there — we sent a confirmation link to ${email}. ` +
              "Open it (check spam too), then come back and sign in."
          );
        }
        // If a session exists (confirmations disabled), the auth listener
        // redirects automatically via the <Navigate> above.
      } else {
        const { error: authError } = await supabase.auth.signInWithPassword({
          email,
          password,
        });
        if (authError) {
          // Common cases: 400 Invalid login credentials, 422 email format, 429 rate limit
          setError(authError.message);
        }
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
      component="main"
      sx={{
        minHeight: "100dvh",
        display: "grid",
        placeItems: "center",
        px: 3,
        py: 6,
        background: brand.ink,
        position: "relative",
        isolation: "isolate",
        overflow: "hidden",
      }}
    >
      <NeoAtmosphere login />
      <Stack
        spacing={4}
        sx={{
          width: "100%",
          maxWidth: 420,
          ml: { xs: 0, md: "44%" },
          position: "relative",
        }}
      >
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <Box
            aria-hidden="true"
            sx={{
              width: 42,
              height: 44,
              display: "grid",
              placeItems: "center",
              border: `1px solid ${brand.magenta}`,
              borderRadius: "4px",
              color: brand.magenta,
              fontFamily: fonts.jp,
              fontSize: 24,
            }}
          >
            記
          </Box>
          <Box>
            <Typography
              sx={{ fontSize: 28, fontWeight: 600, letterSpacing: "-0.03em" }}
            >
              Kioku
            </Typography>
            <Typography sx={{ fontSize: 14, color: brand.muted }}>
              A second brain for your work.
            </Typography>
          </Box>
        </Stack>
        <Box
          component="form"
          onSubmit={handleSubmit}
          sx={{
            p: { xs: 2.5, sm: 4 },
            border: `1px solid ${brand.magenta}`,
            borderTop: `2px solid ${brand.cyan}`,
            boxShadow: neonGlow(brand.magenta, 2),
            borderRadius: 2,
            bgcolor: brand.surface,
          }}
        >
          <Typography component="h1" variant="h4" sx={{ mb: 1 }}>
            {isSignUp ? "Create your account" : "Welcome back"}
          </Typography>
          <Typography sx={{ color: brand.muted, mb: 3, fontSize: 15 }}>
            {isSignUp
              ? "Start building your shared knowledge."
              : "Sign in to your second brain."}
          </Typography>
          <Stack spacing={2.5}>
            <TextField
              InputLabelProps={{ required: false }}
              label="Email"
              type="email"
              fullWidth
              required
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              autoComplete="email"
            />
            <TextField
              InputLabelProps={{ required: false }}
              label="Password"
              type="password"
              fullWidth
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              autoComplete={isSignUp ? "new-password" : "current-password"}
            />
            {error && <Alert severity="error">{error}</Alert>}
            {notice && <Alert severity="success">{notice}</Alert>}
            <Button
              type="submit"
              variant="contained"
              fullWidth
              disabled={loading}
              sx={{ minHeight: 44 }}
            >
              {loading ? (
                <CircularProgress size={22} color="inherit" />
              ) : isSignUp ? (
                "Sign up"
              ) : (
                "Sign in"
              )}
            </Button>
          </Stack>
          <Typography
            sx={{
              color: brand.muted,
              textAlign: "center",
              mt: 3,
              fontSize: 14,
            }}
          >
            {isSignUp ? "Already have an account? " : "Need an account? "}
            <MuiLink
              component="button"
              type="button"
              onClick={() => {
                setIsSignUp(!isSignUp);
                setError("");
                setNotice("");
              }}
              sx={{
                color: brand.magenta,
                fontSize: "inherit",
                fontFamily: "inherit",
                fontWeight: 500,
              }}
            >
              {isSignUp ? "Sign in" : "Sign up"}
            </MuiLink>
          </Typography>
        </Box>
        <Typography
          sx={{ color: brand.dim, textAlign: "center", fontSize: 13 }}
        >
          Your knowledge. Connected across sessions.
        </Typography>
      </Stack>
    </Box>
  );
}
