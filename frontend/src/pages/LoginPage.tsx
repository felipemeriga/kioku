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
import { brand, fonts } from "../theme";
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
      data-testid="login-page"
      sx={{
        minHeight: "100dvh",
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        bgcolor: brand.ink,
        position: "relative",
        isolation: "isolate",
        overflow: "hidden",
        "& [data-testid='login-atmosphere'] > :last-child": { display: "none" },
        "@media(max-width:900px)": { gridTemplateColumns: "1fr" },
      }}
    >
      <NeoAtmosphere login />
      <Box
        component="section"
        data-testid="login-brand"
        sx={{
          p: "65px",
          display: "flex",
          flexDirection: "column",
          borderRight: `1px solid ${brand.line}`,
          background: `linear-gradient(90deg, ${brand.ink}A6, ${brand.ink}22)`,
          minWidth: 0,
          "@media(max-width:1180px)": { p: "45px" },
          "@media(max-width:900px)": {
            p: "30px",
            minHeight: 240,
            borderRight: 0,
            borderBottom: `1px solid ${brand.line}`,
          },
          "@media(max-width:480px)": { p: "25px 22px" },
        }}
      >
        <Stack direction="row" alignItems="center" spacing="13px">
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
          <Box sx={{ "@media(max-width:780px)": { display: "none" } }}>
            <Typography
              sx={{
                fontSize: 11,
                color: brand.muted,
                letterSpacing: 2,
                lineHeight: 1.3,
              }}
            >
              キオク
            </Typography>
            <Typography
              sx={{
                fontSize: 23,
                fontWeight: 600,
                letterSpacing: "-.8px",
                lineHeight: 1.3,
              }}
            >
              kioku
            </Typography>
          </Box>
        </Stack>
        <Box
          sx={{
            my: "auto",
            py: "70px",
            maxWidth: 440,
            textShadow: `0 2px 10px ${brand.ink}`,
            "@media(max-width:900px)": {
              mt: 0,
              pt: "35px",
              pb: 0,
              maxWidth: 600,
            },
          }}
        >
          <Typography
            aria-hidden="true"
            sx={{
              fontSize: 90,
              color: brand.magenta,
              fontFamily: fonts.jp,
              fontWeight: 400,
              lineHeight: 1.1,
              mb: "30px",
              letterSpacing: "10px",
              "@media(max-width:900px)": { display: "none" },
            }}
          >
            記憶
          </Typography>
          <Typography
            component="h1"
            sx={{
              fontSize: 42,
              fontWeight: 600,
              lineHeight: 1.2,
              letterSpacing: "-1.2px",
              mb: "20px",
              "@media(max-width:1180px)": { fontSize: 36 },
              "@media(max-width:900px)": { fontSize: 30, mb: "10px" },
              "@media(max-width:480px)": { fontSize: 27 },
            }}
          >
            Your work deserves
            <br />
            to be remembered.
          </Typography>
          <Typography
            sx={{
              fontSize: 17,
              color: brand.text,
              lineHeight: 1.7,
              maxWidth: "40ch",
              "@media(max-width:900px)": { fontSize: 15 },
            }}
          >
            Documents, repository context, and grounded answers. A second brain
            for the way you build.
          </Typography>
        </Box>
        <Typography
          sx={{
            fontSize: 12,
            color: brand.muted,
            "@media(max-width:900px)": { display: "none" },
          }}
        >
          Kioku · A second brain for your repositories
        </Typography>
      </Box>
      <Box
        component="section"
        data-testid="login-form-side"
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          p: "65px 40px",
          bgcolor: `${brand.ink}F0`,
          "@media(max-width:900px)": { p: "42px 26px" },
          "@media(max-width:480px)": { p: "35px 22px" },
        }}
      >
        <Box
          component="form"
          onSubmit={handleSubmit}
          sx={{ width: "100%", maxWidth: 380 }}
        >
          <Typography
            component="h2"
            sx={{
              fontSize: 29,
              fontWeight: 600,
              lineHeight: 1.3,
              mb: "12px",
              "@media(max-width:480px)": { fontSize: 26 },
            }}
          >
            {isSignUp ? "Create your account" : "Welcome back"}
          </Typography>
          <Typography
            sx={{
              color: brand.muted,
              fontSize: 15,
              lineHeight: 1.65,
              mb: "30px",
            }}
          >
            {isSignUp
              ? "Start building your shared knowledge."
              : "Sign in to continue working with your knowledge."}
          </Typography>
          <Typography
            component="label"
            htmlFor="login-email"
            sx={{ display: "block", fontSize: 14, fontWeight: 500, mb: "8px" }}
          >
            Email
          </Typography>
          <TextField
            id="login-email"
            type="email"
            fullWidth
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            autoComplete="email"
            placeholder="you@example.com"
            size="small"
            sx={{
              mb: "20px",
              "& .MuiInputBase-root": {
                height: 44,
                borderRadius: "4px",
                bgcolor: brand.ink,
                fontSize: 14,
              },
            }}
          />
          <Typography
            component="label"
            htmlFor="login-password"
            sx={{ display: "block", fontSize: 14, fontWeight: 500, mb: "8px" }}
          >
            Password
          </Typography>
          <TextField
            id="login-password"
            type="password"
            fullWidth
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoComplete={isSignUp ? "new-password" : "current-password"}
            placeholder="Enter your password"
            size="small"
            sx={{
              mb: "20px",
              "& .MuiInputBase-root": {
                height: 44,
                borderRadius: "4px",
                bgcolor: brand.ink,
                fontSize: 14,
              },
            }}
          />
          {error && (
            <Alert severity="error" sx={{ mb: "20px" }}>
              {error}
            </Alert>
          )}
          {notice && (
            <Alert severity="success" sx={{ mb: "20px" }}>
              {notice}
            </Alert>
          )}
          <Button
            type="submit"
            variant="contained"
            fullWidth
            disabled={loading}
            sx={{ minHeight: 44, mt: "8px" }}
          >
            {loading ? (
              <CircularProgress size={22} color="inherit" />
            ) : isSignUp ? (
              "Sign up"
            ) : (
              "Sign in"
            )}
          </Button>
          <Typography
            sx={{
              color: brand.muted,
              textAlign: "center",
              mt: "24px",
              fontSize: 14,
            }}
          >
            {isSignUp ? "Already have an account? " : "New to Kioku? "}
            <MuiLink
              component="button"
              type="button"
              aria-label={isSignUp ? "Sign in" : "Sign up"}
              onClick={() => {
                setIsSignUp(!isSignUp);
                setError("");
                setNotice("");
              }}
              sx={{
                color: brand.cyan,
                fontSize: "inherit",
                fontFamily: "inherit",
                p: 0,
              }}
            >
              {isSignUp ? "Sign in" : "Create an account"}
            </MuiLink>
          </Typography>
          <Typography
            sx={{
              fontSize: 15,
              color: brand.muted,
              mt: "20px",
              mb: "30px",
              lineHeight: 1.65,
            }}
          >
            Your knowledge. Connected across sessions.
          </Typography>
        </Box>
      </Box>
    </Box>
  );
}
