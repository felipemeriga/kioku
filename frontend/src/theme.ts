import { createTheme } from "@mui/material/styles";

/**
 * Kioku (記憶) brand tokens — cyberpunk 80s Japan.
 *
 * Palette: neon magenta primary + electric cyan accent on deep purple-black.
 * Type stack: Orbitron for display (angular retrofuture), Inter for body,
 * JetBrains Mono for code/HUD, Noto Sans JP for kanji accents. Every
 * surface pulls from `brand` tokens — recolouring stays one-file trivial.
 *
 * Motion + effect helpers live in `neonGlow()` and `scanlines` — apply
 * per-element to keep the aesthetic without drowning the density.
 */
export const brand = {
  // Neons
  magenta: "#FF2E93",       // primary CTA + brand
  magentaDeep: "#D31877",   // hover, depressed
  magentaGlow: "#FF6DB1",   // gradient stop
  cyan: "#00F0FF",          // secondary + AI/scanning
  cyanDeep: "#00B8CC",
  purple: "#B026FF",        // gradient bridge
  amber: "#FFB700",         // highlight/warning — CRT gold
  amberLight: "#FFD24C",
  green: "#39FF14",         // success / terminal
  red: "#FF3E5F",           // error
  // Base surfaces — deep purple-black
  ink: "#08040F",           // page background
  inkDeep: "#050208",       // deeper stops
  surface: "#0F0820",       // cards, panels
  surface2: "#0A0517",      // sunken card stops
  line: "#2A1758",          // borders — dim electric purple
  lineGlow: "#4B2688",      // hover borders
  // Text
  text: "#F5F0FF",          // primary — slight lavender warmth
  muted: "#9788B8",         // secondary
  dim: "#645A80",           // tertiary
  chrome: "#E4E4E7",        // neutral chrome for HUD elements
  // Aliases for backwards compat during rename sweep
  violet: "#FF2E93",
  violet2: "#B026FF",
  violetDeep: "#D31877",
};

/** Emit a neon glow box-shadow. Use for hero surfaces + focused buttons. */
export const neonGlow = (hex: string, intensity: 1 | 2 | 3 = 2): string => {
  const layer = (px: number, alpha: string) => `0 0 ${px}px ${hex}${alpha}`;
  if (intensity === 1) return layer(8, "55");
  if (intensity === 2) return `${layer(4, "88")}, ${layer(16, "44")}`;
  return `${layer(2, "cc")}, ${layer(8, "aa")}, ${layer(24, "55")}, ${layer(48, "33")}`;
};

/** Subtle CRT scanline overlay. Apply as a background-image on Box wrappers. */
export const scanlines =
  "repeating-linear-gradient(0deg, rgba(255,255,255,0.015) 0px, rgba(255,255,255,0.015) 1px, transparent 1px, transparent 3px)";

// Rubik everywhere — geometric with rounded corners. Cyberpunk vibe
// through the neon palette, not through angular typography. Rubik reads
// beautifully at body sizes AND has enough personality at display sizes.
// Mono kept for code/HUD readouts, Noto Sans JP for kanji glyphs.
const FONT_DISPLAY =
  "'Rubik', system-ui, -apple-system, sans-serif";
const FONT_BODY =
  "'Rubik', 'Noto Sans JP', -apple-system, BlinkMacSystemFont, sans-serif";
const FONT_MONO = "'JetBrains Mono', 'SFMono-Regular', Menlo, monospace";
const FONT_JP = "'Noto Sans JP', 'Yu Gothic', system-ui, sans-serif";

const theme = createTheme({
  palette: {
    mode: "dark",
    primary: {
      main: brand.magenta,
      light: brand.magentaGlow,
      dark: brand.magentaDeep,
    },
    secondary: { main: brand.cyan },
    warning: { main: brand.amber, light: brand.amberLight },
    success: { main: brand.green },
    info: { main: brand.cyan },
    error: { main: brand.red },
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
  // Tighter corners — cyberpunk hardware, not consumer app
  shape: { borderRadius: 4 },
  typography: {
    fontFamily: FONT_BODY,
    h1: { fontFamily: FONT_DISPLAY, fontWeight: 700, letterSpacing: -0.5 },
    h2: { fontFamily: FONT_DISPLAY, fontWeight: 700, letterSpacing: -0.4 },
    h3: { fontFamily: FONT_DISPLAY, fontWeight: 700, letterSpacing: -0.3 },
    h4: { fontFamily: FONT_DISPLAY, fontWeight: 700, letterSpacing: -0.2 },
    h5: { fontFamily: FONT_DISPLAY, fontWeight: 600, letterSpacing: -0.1 },
    h6: { fontFamily: FONT_DISPLAY, fontWeight: 600, letterSpacing: 0 },
    subtitle1: { fontFamily: FONT_DISPLAY, fontWeight: 500 },
    subtitle2: { fontFamily: FONT_DISPLAY, fontWeight: 500 },
    button: {
      fontFamily: FONT_DISPLAY,
      fontWeight: 600,
      textTransform: "none",
      letterSpacing: 0.1,
    },
    overline: {
      fontFamily: FONT_MONO,
      fontWeight: 500,
      letterSpacing: "0.22em",
      textTransform: "uppercase",
    },
    caption: { fontFamily: FONT_BODY, fontWeight: 400 },
    body1: { fontFamily: FONT_BODY, fontWeight: 400, lineHeight: 1.55 },
    body2: { fontFamily: FONT_BODY, fontWeight: 400, lineHeight: 1.55 },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundColor: brand.ink,
          // Dual-neon ambient: magenta bloom top-left, cyan bloom bottom-right.
          // Combined with subtle scanlines for CRT texture.
          backgroundImage: `
            radial-gradient(circle at 8% -6%, ${brand.magenta}22 0%, transparent 45%),
            radial-gradient(circle at 92% 108%, ${brand.cyan}18 0%, transparent 45%),
            ${scanlines}
          `,
          backgroundAttachment: "fixed",
          minHeight: "100vh",
        },
        "*::-webkit-scrollbar": { width: 10, height: 10 },
        "*::-webkit-scrollbar-track": { background: brand.inkDeep },
        "*::-webkit-scrollbar-thumb": {
          background: brand.line,
          borderRadius: 4,
          border: `2px solid ${brand.inkDeep}`,
        },
        "*::-webkit-scrollbar-thumb:hover": { background: brand.magenta },
        // Selection color — cyan neon
        "::selection": {
          background: `${brand.cyan}55`,
          color: brand.text,
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
          backgroundColor: brand.surface,
          border: `1px solid ${brand.line}`,
          boxShadow:
            "0 1px 0 rgba(255,255,255,0.03), 0 12px 32px rgba(0,0,0,0.55)",
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          background: `linear-gradient(180deg, ${brand.surface} 0%, ${brand.surface2} 100%)`,
          border: `1px solid ${brand.line}`,
        },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: { borderRadius: 4, fontWeight: 600 },
        contained: {
          backgroundImage: `linear-gradient(90deg, ${brand.magenta} 0%, ${brand.purple} 100%)`,
          color: "#fff",
          boxShadow: `0 4px 12px ${brand.magenta}44`,
          "&:hover": {
            backgroundImage: `linear-gradient(90deg, ${brand.magentaDeep} 0%, ${brand.magenta} 100%)`,
            boxShadow: `0 6px 20px ${brand.magenta}66, 0 0 24px ${brand.magenta}33`,
          },
        },
        outlined: {
          borderColor: brand.line,
          color: brand.text,
          "&:hover": {
            borderColor: brand.magenta,
            backgroundColor: `${brand.magenta}12`,
            boxShadow: `0 0 12px ${brand.magenta}33`,
          },
        },
        text: { "&:hover": { backgroundColor: `${brand.magenta}14` } },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { fontFamily: FONT_MONO, fontWeight: 500, borderRadius: 3, letterSpacing: 0.5 },
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
          borderRadius: 4,
          "& .MuiOutlinedInput-notchedOutline": { borderColor: brand.line },
          "&:hover .MuiOutlinedInput-notchedOutline": {
            borderColor: brand.lineGlow,
          },
          "&.Mui-focused .MuiOutlinedInput-notchedOutline": {
            borderColor: brand.magenta,
            boxShadow: `0 0 12px ${brand.magenta}44`,
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
          borderBottom: `1px solid ${brand.line}`,
        },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: 3,
          margin: "2px 8px",
          "&.Mui-selected": {
            backgroundColor: `${brand.magenta}22`,
            color: brand.text,
            borderLeft: `2px solid ${brand.magenta}`,
            "& .MuiListItemIcon-root": { color: brand.magenta },
            "&:hover": { backgroundColor: `${brand.magenta}33` },
          },
          "&:hover": { backgroundColor: `${brand.magenta}10` },
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
          letterSpacing: 0.1,
        },
      },
    },
    MuiIconButton: {
      styleOverrides: {
        root: {
          borderRadius: 3,
          "&:hover": { backgroundColor: `${brand.magenta}14` },
        },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          backgroundColor: brand.surface,
          border: `1px solid ${brand.magenta}55`,
          borderRadius: 4,
          fontSize: "0.75rem",
          fontWeight: 500,
          fontFamily: FONT_BODY,
        },
      },
    },
  },
});

// Fonts exported for components that want the literal stack.
export const fonts = {
  display: FONT_DISPLAY,
  body: FONT_BODY,
  mono: FONT_MONO,
  jp: FONT_JP,
};

export default theme;
