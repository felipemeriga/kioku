import { createTheme } from "@mui/material/styles";

/** Neon Tokyo: saturated signal colors over dark, readable knowledge surfaces. */
export const brand = {
  magenta: "#FF1493",
  magentaDeep: "#CE0078",
  magentaGlow: "#FF6DC5",
  cyan: "#00F0FF",
  cyanDeep: "#00BDDB",
  purple: "#B347FF",
  amber: "#FFC247",
  amberLight: "#FFE095",
  green: "#4FFF9A",
  red: "#FF5D81",
  ink: "#070510",
  inkDeep: "#04020A",
  surface: "#12091F",
  surface2: "#0D0718",
  raised: "#221035",
  line: "#654B83",
  lineGlow: "#B06AFF",
  text: "#FAF7FF",
  muted: "#E0D5F3",
  dim: "#BEB0D7",
  chrome: "#E4DEED",
  violet: "#FF1493",
  violet2: "#B347FF",
  violetDeep: "#CE0078",
};
const FONT_BODY =
  "'IBM Plex Sans', 'Noto Sans JP', -apple-system, BlinkMacSystemFont, sans-serif";
const FONT_MONO = "'IBM Plex Mono', 'SFMono-Regular', Menlo, monospace";
const FONT_JP =
  "'Noto Sans JP', 'Hiragino Kaku Gothic ProN', 'Yu Gothic', sans-serif";
export const fonts = {
  display: FONT_BODY,
  body: FONT_BODY,
  mono: FONT_MONO,
  jp: FONT_JP,
  dot: FONT_JP,
};
/** Restrained light on interactive edges; reading surfaces stay opaque. */
export const neonGlow = (hex: string, intensity: 1 | 2 | 3 = 2): string =>
  `0 0 ${6 * intensity}px ${hex}44, 0 0 ${14 * intensity}px ${hex}18`;
export const scanlines = "none";
export const STATUS_GLYPH = {
  pinned: { glyph: "●", color: brand.magenta, glow: "none" },
  hybrid: { glyph: "◐", color: brand.cyan, glow: "none" },
  auto: { glyph: "○", color: brand.muted, glow: "none" },
};

const theme = createTheme({
  palette: {
    mode: "dark",
    primary: {
      main: brand.magenta,
      light: brand.magentaGlow,
      dark: brand.magentaDeep,
      contrastText: brand.ink,
    },
    secondary: { main: brand.cyan },
    warning: { main: brand.amber, light: brand.amberLight },
    success: { main: brand.green },
    info: { main: brand.cyan },
    error: { main: brand.red },
    background: { default: brand.ink, paper: brand.surface },
    text: { primary: brand.text, secondary: brand.muted },
    divider: brand.line,
  },
  shape: { borderRadius: 4 },
  typography: {
    fontFamily: FONT_BODY,
    h1: {
      fontSize: "2rem",
      lineHeight: 1.2,
      fontWeight: 600,
      letterSpacing: "-0.035em",
    },
    h2: {
      fontSize: "1.75rem",
      lineHeight: 1.25,
      fontWeight: 600,
      letterSpacing: "-0.025em",
    },
    h3: { fontSize: "1.5rem", fontWeight: 600 },
    h4: { fontSize: "1.375rem", fontWeight: 600 },
    h5: { fontSize: "1.25rem", fontWeight: 600 },
    h6: { fontSize: "1.125rem", fontWeight: 600 },
    subtitle1: { fontWeight: 500 },
    subtitle2: { fontWeight: 500 },
    body1: { fontSize: "1rem", lineHeight: 1.7 },
    body2: { fontSize: "0.9375rem", lineHeight: 1.6 },
    caption: { fontSize: "0.8125rem", lineHeight: 1.5 },
    overline: {
      fontFamily: FONT_BODY,
      fontSize: "0.8125rem",
      fontWeight: 500,
      letterSpacing: 0,
      textTransform: "none",
    },
    button: {
      fontWeight: 600,
      textTransform: "none",
      letterSpacing: 0,
      fontSize: "0.875rem",
    },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        ":root": {
          "--kioku-line": brand.line,
          "--kioku-control": brand.lineGlow,
          "--kioku-surface": brand.surface,
          "--kioku-sunken": brand.surface2,
          "--kioku-accent": brand.magenta,
        },
        html: { height: "100%", colorScheme: "dark" },
        body: { background: brand.ink, minHeight: "100vh", margin: 0 },
        "#root": { minHeight: "100vh" },
        "*": { boxSizing: "border-box" },
        ":focus-visible": {
          outline: `2px solid ${brand.cyan}`,
          outlineOffset: 3,
        },
        "::selection": { background: `${brand.cyan}44`, color: brand.text },
        "*::-webkit-scrollbar": { width: 8, height: 8 },
        "*::-webkit-scrollbar-track": { background: brand.ink },
        "*::-webkit-scrollbar-thumb": {
          background: brand.lineGlow,
          borderRadius: 8,
          border: `2px solid ${brand.ink}`,
        },
        "code, pre, kbd": { fontFamily: FONT_MONO },
        "@media (prefers-reduced-motion: reduce)": {
          "*, *::before, *::after": {
            animation: "none !important",
            scrollBehavior: "auto !important",
            transition: "none !important",
          },
        },
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: "none",
          backgroundColor: brand.surface,
          border: `1px solid ${brand.line}`,
          boxShadow: "none",
        },
      },
    },
    MuiCard: {
      styleOverrides: {
        root: { background: brand.surface, border: `1px solid ${brand.line}` },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: {
          borderRadius: 4,
          minHeight: 44,
          padding: "10px 16px",
          fontSize: 14,
          fontWeight: 600,
          boxShadow: "none",
        },
        contained: {
          background: brand.magenta,
          color: brand.ink,
          boxShadow: neonGlow(brand.magenta, 1),
          "&:hover": {
            background: brand.magentaGlow,
            boxShadow: neonGlow(brand.magenta, 2),
          },
        },
        outlined: {
          borderColor: brand.lineGlow,
          color: brand.text,
          "&:hover": { borderColor: brand.muted, background: brand.raised },
        },
        text: { "&:hover": { background: brand.raised } },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: {
          fontFamily: FONT_BODY,
          fontSize: "0.8125rem",
          fontWeight: 500,
          borderRadius: 4,
          letterSpacing: 0,
        },
        outlined: { borderColor: brand.lineGlow },
      },
    },
    MuiTextField: { defaultProps: { variant: "outlined" } },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          background: brand.surface2,
          borderRadius: 4,
          "& .MuiOutlinedInput-notchedOutline": { borderColor: brand.lineGlow },
          "&:hover .MuiOutlinedInput-notchedOutline": {
            borderColor: brand.muted,
          },
          "&.Mui-focused .MuiOutlinedInput-notchedOutline": {
            borderColor: brand.cyan,
          },
          "&.Mui-focused": { boxShadow: neonGlow(brand.cyan, 1) },
        },
      },
    },
    MuiInputLabel: {
      styleOverrides: { root: { color: brand.muted, fontFamily: FONT_BODY } },
    },
    MuiDrawer: {
      styleOverrides: {
        paper: {
          background: brand.surface2,
          borderRight: `1px solid ${brand.line}`,
        },
      },
    },
    MuiAppBar: {
      styleOverrides: {
        root: {
          background: brand.ink,
          borderBottom: `1px solid ${brand.line}`,
          boxShadow: "none",
        },
      },
    },
    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: 4,
          margin: "2px 8px",
          "&.Mui-selected": {
            background: `${brand.magenta}20`,
            color: brand.text,
            boxShadow: `inset 2px 0 ${brand.magenta}, 0 0 14px ${brand.magenta}16`,
            outline: `1px solid ${brand.magenta}66`,
            "&:hover": { background: `${brand.magenta}20` },
          },
          "&:hover": { background: brand.raised },
        },
      },
    },
    MuiDivider: { styleOverrides: { root: { borderColor: brand.line } } },
    MuiAvatar: {
      styleOverrides: { root: { fontFamily: FONT_BODY, fontWeight: 600 } },
    },
    MuiTab: {
      styleOverrides: {
        root: {
          fontWeight: 500,
          textTransform: "none",
          letterSpacing: 0,
          minHeight: 48,
          fontSize: "0.9375rem",
          "&.Mui-selected": {
            color: brand.cyan,
            textShadow: `0 0 12px ${brand.cyan}44`,
          },
        },
      },
    },
    MuiTabs: {
      styleOverrides: { indicator: { boxShadow: neonGlow(brand.cyan, 1) } },
      defaultProps: {
        variant: "scrollable",
        scrollButtons: "auto",
        allowScrollButtonsMobile: true,
      },
    },
    MuiIconButton: {
      styleOverrides: {
        root: { borderRadius: 4, "&:hover": { background: brand.raised } },
      },
    },
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          background: brand.raised,
          border: `1px solid ${brand.lineGlow}`,
          fontSize: "0.8125rem",
          fontWeight: 400,
          fontFamily: FONT_BODY,
        },
      },
    },
    MuiDialog: {
      styleOverrides: { paper: { background: brand.surface, borderRadius: 8 } },
    },
    MuiDialogTitle: {
      styleOverrides: { root: { fontSize: "1.25rem", fontWeight: 600 } },
    },
    MuiTableCell: {
      styleOverrides: {
        root: { fontSize: "0.875rem", borderColor: brand.line },
        head: {
          fontWeight: 500,
          color: brand.muted,
          background: brand.surface2,
        },
      },
    },
    MuiAlert: {
      styleOverrides: {
        root: { borderRadius: 6, fontSize: "0.875rem", lineHeight: 1.6 },
      },
    },
  },
});
export default theme;
