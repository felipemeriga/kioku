import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
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

  if (!authLoading && session) {
    return <Navigate to="/" replace />;
  }

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    const { error: authError } = isSignUp
      ? await supabase.auth.signUp({ email, password })
      : await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);
    if (authError) setError(authError.message);
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

        {/* Logo + wordmark */}
        <Stack direction="row" alignItems="center" spacing={1.5}>
          <Box
            component="img"
            src="/logo.svg"
            alt="Agentic RAG"
            sx={{ width: 40, height: 40, borderRadius: 1.5, boxShadow: `0 6px 20px ${alpha(brand.violet, 0.55)}` }}
          />
          <Typography
            sx={{
              fontFamily: fonts.display,
              fontSize: "1.75rem",
              fontWeight: 700,
              letterSpacing: "-0.02em",
            }}
          >
            AGENTIC{" "}
            <Box component="span" sx={{ color: brand.violet2 }}>
              RAG
            </Box>
          </Typography>
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
              ? "Sign up to start feeding your personal knowledge agent."
              : "Sign in to keep feeding your personal knowledge agent."}
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
