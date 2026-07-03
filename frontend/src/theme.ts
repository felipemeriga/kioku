import { createTheme } from "@mui/material/styles";

/**
 * Agentic RAG brand tokens — adopted from Role Miner brand guide.
 *
 * Three font families (Space Grotesk for display, Inter for body,
 * JetBrains Mono for code/overline). Five accent colors on ink-dark
 * surfaces. Every surface should reach for `brand` tokens rather than
 * inlining hex literals — keeps future recolouring trivial.
 */
export const brand = {
  violet: "#7C3AED", // primary CTA + nav highlight
  violet2: "#A855F7", // secondary, gradient stop
  violetDeep: "#6D28D9", // deepest stop
  cyan: "#22D3EE", // AI / scanning / active
  amber: "#F59E0B", // highlights, warnings
  amberLight: "#FBBF24",
  green: "#10B981", // success
  ink: "#0B1020", // page background
  surface: "#151B2F", // cards, panels
  surface2: "#0E1424", // sunken card stops
  line: "#222B45", // borders, dividers
  text: "#F8FAFC", // primary text
  muted: "#9FB0C9", // secondary text
};

const FONT_DISPLAY = "'Space Grotesk', system-ui, -apple-system, sans-serif";
const FONT_BODY = "'Inter', -apple-system, BlinkMacSystemFont, sans-serif";
const FONT_MONO = "'JetBrains Mono', 'SFMono-Regular', Menlo, monospace";

const theme = createTheme({
  palette: {
    mode: "dark",
    primary: { main: brand.violet, light: brand.violet2, dark: brand.violetDeep },
    secondary: { main: brand.cyan },
    warning: { main: brand.amber, light: brand.amberLight },
    success: { main: brand.green },
    info: { main: brand.cyan },
    error: { main: "#ef4444" },
    background: {
      default: brand.ink,
      paper: brand.surface,
    },
    text: {
      primary: brand.text,
      secondary: brand.muted,
    },
    divider: brand.line,
  },
  shape: { borderRadius: 14 },
  typography: {
    fontFamily: FONT_BODY,
    h1: { fontFamily: FONT_DISPLAY, fontWeight: 700, letterSpacing: -0.5 },
    h2: { fontFamily: FONT_DISPLAY, fontWeight: 700, letterSpacing: -0.5 },
    h3: { fontFamily: FONT_DISPLAY, fontWeight: 700, letterSpacing: -0.3 },
    h4: { fontFamily: FONT_DISPLAY, fontWeight: 700 },
    h5: { fontFamily: FONT_DISPLAY, fontWeight: 700 },
    h6: { fontFamily: FONT_DISPLAY, fontWeight: 700 },
    subtitle1: { fontFamily: FONT_DISPLAY, fontWeight: 600 },
    subtitle2: { fontFamily: FONT_DISPLAY, fontWeight: 600 },
    button: {
      fontFamily: FONT_DISPLAY,
      fontWeight: 600,
      textTransform: "none",
      letterSpacing: 0.1,
    },
    overline: { fontFamily: FONT_MONO, fontWeight: 500, letterSpacing: "0.18em" },
    caption: { fontFamily: FONT_BODY },
    body1: { fontFamily: FONT_BODY, lineHeight: 1.55 },
    body2: { fontFamily: FONT_BODY, lineHeight: 1.55 },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundColor: brand.ink,
          // Subtle violet+cyan ambient glow so every surface inherits the mood.
          backgroundImage: `radial-gradient(circle at 12% -8%, ${brand.violet}22 0%, transparent 45%), radial-gradient(circle at 92% 110%, ${brand.cyan}10 0%, transparent 45%)`,
          backgroundAttachment: "fixed",
          minHeight: "100vh",
        },
        "*::-webkit-scrollbar": { width: 10, height: 10 },
        "*::-webkit-scrollbar-track": { background: brand.surface2 },
        "*::-webkit-scrollbar-thumb": {
          background: "#2B3550",
          borderRadius: 6,
          border: `2px solid ${brand.surface2}`,
        },
        "*::-webkit-scrollbar-thumb:hover": { background: brand.violet },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
          backgroundColor: brand.surface,
          border: `1px solid ${brand.line}`,
          boxShadow:
            "0 1px 0 rgba(255,255,255,0.03), 0 12px 32px rgba(0,0,0,0.45)",
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          background: `linear-gradient(180deg, ${brand.surface} 0%, ${brand.surface2} 100%)`,
        },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: { borderRadius: 10, fontWeight: 600 },
        contained: {
          backgroundImage: `linear-gradient(90deg, ${brand.violet} 0%, ${brand.violet2} 100%)`,
          color: "#fff",
          "&:hover": {
            backgroundImage: `linear-gradient(90deg, ${brand.violetDeep} 0%, ${brand.violet} 100%)`,
            boxShadow: `0 6px 20px ${brand.violet}55`,
          },
        },
        outlined: {
          borderColor: brand.line,
          "&:hover": {
            borderColor: brand.violet2,
            backgroundColor: `${brand.violet}10`,
          },
        },
        text: { "&:hover": { backgroundColor: `${brand.violet}14` } },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontFamily: FONT_BODY, fontWeight: 500, borderRadius: 8 },
        outlined: { borderColor: brand.line },
      },
    },
    MuiTextField: {
      defaultProps: { variant: "outlined" },
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          backgroundColor: brand.surface2,
          "& .MuiOutlinedInput-notchedOutline": { borderColor: brand.line },
          "&:hover .MuiOutlinedInput-notchedOutline": {
            borderColor: brand.violet2,
          },
          "&.Mui-focused .MuiOutlinedInput-notchedOutline": {
            borderColor: brand.violet,
          },
        },
      },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: brand.surface2,
          backgroundImage: "none",
          borderRight: `1px solid ${brand.line}`,
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
          backgroundColor: `${brand.ink}cc`,
        },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: 10,
          margin: "2px 8px",
          "&.Mui-selected": {
            backgroundColor: `${brand.violet}22`,
            color: brand.text,
            "& .MuiListItemIcon-root": { color: brand.violet2 },
            "&:hover": { backgroundColor: `${brand.violet}33` },
          },
          "&:hover": { backgroundColor: `${brand.violet}12` },
        },
      },
    },
    MuiDivider: {
      styleOverrides: { root: { borderColor: brand.line } },
    },
    MuiAvatar: {
      styleOverrides: {
        root: { fontFamily: FONT_DISPLAY, fontWeight: 700 },
      },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          fontFamily: FONT_DISPLAY,
          fontWeight: 600,
          textTransform: "none",
        },
      },
    },
    MuiIconButton: {
      styleOverrides: {
        root: {
          borderRadius: 10,
          "&:hover": { backgroundColor: `${brand.violet}14` },
        },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          backgroundColor: brand.surface,
          border: `1px solid ${brand.line}`,
          borderRadius: 8,
          fontSize: "0.75rem",
          fontWeight: 500,
          fontFamily: FONT_BODY,
        },
      },
    },
  },
});

// Fonts exported for components that want the literal stack (code blocks, etc.)
export const fonts = {
  display: FONT_DISPLAY,
  body: FONT_BODY,
  mono: FONT_MONO,
};

export default theme;
