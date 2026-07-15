import { useState, type FormEvent } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import { safeRedirect } from "../lib/redirect";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Divider,
  Link as MuiLink,
  Stack,
  TextField,
  Typography,
  alpha,
} from "@mui/material";
import { supabase } from "../lib/supabase";
import { useAuth } from "../hooks/useAuth";
import { brand, fonts } from "../theme";

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
        ? await supabase.auth.signUp({ email, password })
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
          : "Couldn't reach the sign-in service. Check your internet connection.",
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
        alignItems: "center",
        justifyContent: "center",
        position: "relative",
        overflow: "hidden",
        bgcolor: brand.ink,
        px: 2,
      }}
    >
      <Box
        data-testid="ambient-bg"
        sx={{
          position: "absolute",
          inset: 0,
          background: `
            radial-gradient(ellipse 600px 600px at 20% 30%, ${alpha(brand.violet, 0.18)} 0%, transparent 70%),
            radial-gradient(ellipse 500px 500px at 80% 70%, ${alpha(brand.cyan, 0.12)} 0%, transparent 70%),
            radial-gradient(ellipse 400px 400px at 50% 50%, ${alpha(brand.violetDeep, 0.1)} 0%, transparent 70%)
          `,
          animation: "meshDrift 24s ease-in-out infinite",
          "@keyframes meshDrift": {
            "0%": { backgroundPosition: "0% 0%, 100% 100%, 50% 50%" },
            "33%": { backgroundPosition: "30% 20%, 70% 80%, 40% 60%" },
            "66%": { backgroundPosition: "10% 40%, 90% 60%, 60% 30%" },
            "100%": { backgroundPosition: "0% 0%, 100% 100%, 50% 50%" },
          },
          backgroundSize: "200% 200%",
        }}
      />

      <Stack spacing={2.75} alignItems="center" sx={{ position: "relative", width: "100%", maxWidth: 400 }}>
        {/* Brand chip */}
        <Box
          sx={{
            px: 1.5,
            py: 0.6,
            border: `1px solid ${alpha(brand.cyan, 0.4)}`,
            borderRadius: 999,
            bgcolor: alpha(brand.cyan, 0.06),
          }}
        >
          <Typography
            sx={{
              fontFamily: fonts.mono,
              fontSize: "0.66rem",
              letterSpacing: "0.28em",
              color: brand.cyan,
              display: "flex",
              alignItems: "center",
              gap: 0.85,
            }}
          >
            <Box component="span" sx={{ width: 6, height: 6, borderRadius: "50%", bgcolor: brand.cyan, boxShadow: `0 0 8px ${brand.cyan}` }} />
            AI · PERSONAL KNOWLEDGE AGENT
          </Typography>
        </Box>

        {/* Kanji hanko + wordmark */}
        <Stack direction="row" alignItems="center" spacing={1.75}>
          <Box
            sx={{
              width: 44,
              height: 44,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              border: `1px solid ${brand.magenta}`,
              borderRadius: 1,
              background: `linear-gradient(135deg, ${brand.magenta}22 0%, ${brand.cyan}11 100%)`,
              boxShadow: `0 0 18px ${alpha(brand.magenta, 0.6)}, inset 0 0 10px ${alpha(brand.magenta, 0.25)}`,
              fontFamily: fonts.jp,
              fontWeight: 900,
              fontSize: "1.6rem",
              color: brand.magentaGlow,
              textShadow: `0 0 8px ${brand.magenta}, 0 0 16px ${brand.magenta}aa`,
            }}
          >
            記
          </Box>
          <Stack spacing={0.25}>
            <Typography
              sx={{
                fontFamily: fonts.jp,
                fontSize: "0.72rem",
                letterSpacing: "0.35em",
                color: brand.cyan,
                textShadow: `0 0 6px ${brand.cyan}66`,
                lineHeight: 1,
              }}
            >
              キオク
            </Typography>
            <Typography
              sx={{
                fontFamily: fonts.display,
                fontSize: "1.75rem",
                fontWeight: 700,
                letterSpacing: "-0.02em",
                lineHeight: 1.1,
              }}
            >
              Kioku
            </Typography>
          </Stack>
        </Stack>

        {/* Card */}
        <Box
          component="form"
          onSubmit={handleSubmit}
          sx={{
            width: "100%",
            p: 3.5,
            borderRadius: 3,
            bgcolor: alpha(brand.surface, 0.72),
            backdropFilter: "blur(20px)",
            WebkitBackdropFilter: "blur(20px)",
            border: `1px solid ${brand.line}`,
            boxShadow: "0 20px 50px rgba(0,0,0,0.5)",
          }}
        >
          <Typography
            sx={{
              fontFamily: fonts.display,
              fontWeight: 700,
              fontSize: "1.3rem",
              color: brand.text,
              mb: 0.5,
            }}
          >
            {isSignUp ? "Create your account" : "Welcome back"}
          </Typography>
          <Typography sx={{ fontFamily: fonts.body, fontSize: "0.85rem", color: brand.muted, mb: 2.5 }}>
            {isSignUp
              ? "Sign up to start building your second brain."
              : "Sign in to your second brain."}
          </Typography>

          <Stack spacing={1.75}>
            <TextField
              label="Email"
              type="email"
              fullWidth
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              InputLabelProps={{ required: false }}
              autoComplete="email"
            />
            <TextField
              label="Password"
              type="password"
              fullWidth
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              InputLabelProps={{ required: false }}
              autoComplete={isSignUp ? "new-password" : "current-password"}
            />

            {error && <Alert severity="error">{error}</Alert>}

            <Button type="submit" variant="contained" fullWidth disabled={loading} sx={{ py: 1.25, mt: 0.5 }}>
              {loading ? <CircularProgress size={22} color="inherit" /> : isSignUp ? "Sign up" : "Sign in"}
            </Button>

            <Divider sx={{ my: 0.5, "&::before, &::after": { borderColor: brand.line } }}>
              <Typography
                sx={{
                  fontFamily: fonts.mono,
                  fontSize: "0.68rem",
                  letterSpacing: "0.24em",
                  color: brand.muted,
                }}
              >
                OR
              </Typography>
            </Divider>

            <Typography sx={{ fontFamily: fonts.body, fontSize: "0.85rem", color: brand.muted, textAlign: "center" }}>
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
          </Stack>
        </Box>

        {/* Footer tagline */}
        <Typography
          sx={{
            fontFamily: fonts.mono,
            fontSize: "0.65rem",
            letterSpacing: "0.32em",
            color: brand.muted,
            mt: 1,
          }}
        >
          FEED IT{" "}
          <Box component="span" sx={{ color: brand.amber }}>
            EVERYTHING
          </Box>
          . ASK{" "}
          <Box component="span" sx={{ color: brand.cyan }}>
            ANYTHING
          </Box>
          .
        </Typography>
      </Stack>
    </Box>
  );
}
