import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";
import { Alert, Box, Button, Stack, Typography } from "@mui/material";
import { brand, fonts } from "../theme";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Catches render-time crashes and shows a recoverable UI instead of a
 * white screen. Reload button is a hard fallback; the "Try again" button
 * clears the error and re-renders — useful when the failure was a transient
 * fetch that populated some bad state.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // eslint-disable-next-line no-console
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;

    return (
      <Box
        sx={{
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          bgcolor: brand.ink,
          p: 4,
        }}
      >
        <Box
          sx={{
            maxWidth: 560,
            width: "100%",
            border: `1px solid ${brand.line}`,
            borderRadius: 2,
            bgcolor: brand.surface,
            p: 4,
            textAlign: "center",
          }}
        >
          <Typography
            sx={{
              fontFamily: fonts.display,
              fontSize: "1.25rem",
              fontWeight: 600,
              color: brand.text,
              mb: 1,
            }}
          >
            Something crashed.
          </Typography>
          <Typography
            sx={{
              fontFamily: fonts.body,
              fontSize: "0.9rem",
              color: brand.muted,
              mb: 3,
            }}
          >
            The app hit an unexpected error while rendering this page.
          </Typography>
          {this.state.error?.message && (
            <Alert
              severity="error"
              variant="outlined"
              sx={{ mb: 3, textAlign: "left", fontFamily: fonts.mono, fontSize: "0.75rem" }}
            >
              {this.state.error.message}
            </Alert>
          )}
          <Stack direction="row" spacing={1.5} justifyContent="center">
            <Button
              variant="outlined"
              onClick={() => this.setState({ error: null })}
              sx={{ fontFamily: fonts.body }}
            >
              Try again
            </Button>
            <Button
              variant="contained"
              onClick={() => window.location.reload()}
              sx={{ fontFamily: fonts.body, bgcolor: brand.violet }}
            >
              Reload
            </Button>
          </Stack>
        </Box>
      </Box>
    );
  }
}
