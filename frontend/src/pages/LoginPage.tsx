import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import {
  Box,
  TextField,
  Button,
  Typography,
  Alert,
  alpha,
  CircularProgress,
} from "@mui/material";
import { supabase } from "../lib/supabase";
import { useAuth } from "../hooks/useAuth";

export default function LoginPage() {
  const { session, loading: authLoading } = useAuth();
  const [isSignUp, setIsSignUp] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // If we're already signed in (either persisted session or onAuthStateChange
  // just fired after a successful sign-in/sign-up), bounce to the app.
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
        bgcolor: "#0f0f14",
      }}
    >
      {/* Ambient animated background */}
      <Box
        data-testid="ambient-bg"
        sx={{
          position: "absolute",
          inset: 0,
          background: `
            radial-gradient(ellipse 600px 600px at 20% 30%, rgba(124,58,237,0.15) 0%, transparent 70%),
            radial-gradient(ellipse 500px 500px at 80% 70%, rgba(59,130,246,0.12) 0%, transparent 70%),
            radial-gradient(ellipse 400px 400px at 50% 50%, rgba(91,33,182,0.08) 0%, transparent 70%)
          `,
          animation: "meshDrift 20s ease-in-out infinite",
          "@keyframes meshDrift": {
            "0%": { backgroundPosition: "0% 0%, 100% 100%, 50% 50%" },
            "33%": { backgroundPosition: "30% 20%, 70% 80%, 40% 60%" },
            "66%": { backgroundPosition: "10% 40%, 90% 60%, 60% 30%" },
            "100%": { backgroundPosition: "0% 0%, 100% 100%, 50% 50%" },
          },
          backgroundSize: "200% 200%",
        }}
      />

      {/* Glassmorphic card */}
      <Box
        component="form"
        onSubmit={handleSubmit}
        sx={{
          position: "relative",
          width: "100%",
          maxWidth: 400,
          mx: 2,
          p: 4,
          borderRadius: 4,
          bgcolor: alpha("#171720", 0.6),
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
          border: 1,
          borderColor: alpha("#7c3aed", 0.15),
          boxShadow: "0 8px 32px rgba(0,0,0,0.4)",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 2.5,
        }}
      >
        {/* Logo + title */}
        <Box
          component="img"
          src="/logo.svg"
          alt="Agentic RAG"
          sx={{
            width: 56,
            height: 56,
            borderRadius: 3,
          }}
        />
        <Typography
          variant="h5"
          sx={{
            fontWeight: 700,
            background: "linear-gradient(135deg, #7c3aed, #3b82f6)",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
          }}
        >
          Agentic RAG
        </Typography>

        {/* Tab toggle */}
        <Box
          sx={{
            display: "flex",
            gap: 0.5,
            p: 0.5,
            bgcolor: alpha("#ffffff", 0.03),
            borderRadius: 2,
            width: "100%",
          }}
        >
          <Box
            role="tab"
            aria-selected={!isSignUp}
            onClick={() => { setIsSignUp(false); setError(""); }}
            sx={{
              flex: 1,
              textAlign: "center",
              borderRadius: 1.5,
              py: 0.6,
              fontSize: "0.8125rem",
              fontWeight: 500,
              cursor: "pointer",
              userSelect: "none",
              bgcolor: !isSignUp ? alpha("#7c3aed", 0.15) : "transparent",
              color: !isSignUp ? "#a78bfa" : alpha("#ffffff", 0.4),
              "&:hover": {
                bgcolor: !isSignUp ? alpha("#7c3aed", 0.2) : alpha("#ffffff", 0.05),
              },
            }}
          >
            Sign In
          </Box>
          <Box
            role="tab"
            aria-selected={isSignUp}
            onClick={() => { setIsSignUp(true); setError(""); }}
            sx={{
              flex: 1,
              textAlign: "center",
              borderRadius: 1.5,
              py: 0.6,
              fontSize: "0.8125rem",
              fontWeight: 500,
              cursor: "pointer",
              userSelect: "none",
              bgcolor: isSignUp ? alpha("#7c3aed", 0.15) : "transparent",
              color: isSignUp ? "#a78bfa" : alpha("#ffffff", 0.4),
              "&:hover": {
                bgcolor: isSignUp ? alpha("#7c3aed", 0.2) : alpha("#ffffff", 0.05),
              },
            }}
          >
            Sign Up
          </Box>
        </Box>

        {/* Form fields */}
        <TextField label="Email" type="email" fullWidth required value={email} onChange={(e) => setEmail(e.target.value)} InputLabelProps={{ required: false }} />
        <TextField label="Password" type="password" fullWidth required value={password} onChange={(e) => setPassword(e.target.value)} InputLabelProps={{ required: false }} />

        {error && <Alert severity="error" sx={{ width: "100%" }}>{error}</Alert>}

        <Button type="submit" variant="contained" fullWidth disabled={loading} sx={{ py: 1.2 }}>
          {loading ? <CircularProgress size={22} color="inherit" /> : isSignUp ? "Sign Up" : "Sign In"}
        </Button>

        <Typography variant="caption" sx={{ color: alpha("#ffffff", 0.4) }}>
          {isSignUp ? "Already have an account? " : "Don't have an account? "}
          <Typography
            component="span"
            variant="caption"
            onClick={() => { setIsSignUp(!isSignUp); setError(""); }}
            sx={{ color: "#a78bfa", cursor: "pointer", "&:hover": { textDecoration: "underline" } }}
          >
            {isSignUp ? "Sign in" : "Sign up"}
          </Typography>
        </Typography>
      </Box>
    </Box>
  );
}
