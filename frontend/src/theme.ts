import { createTheme } from "@mui/material/styles";

/** Quiet signal: readable knowledge surfaces with Kioku's magenta/cyan identity. */
export const brand = {
  magenta: "#FF69B4",
  magentaDeep: "#EB53A1",
  magentaGlow: "#FF98CB",
  cyan: "#7BDFEA",
  cyanDeep: "#4CC5D3",
  purple: "#BEA0EF",
  amber: "#F3CA82",
  amberLight: "#FFDEA5",
  green: "#97DBB0",
  red: "#FF9BAF",
  ink: "#0C0914",
  inkDeep: "#09060F",
  surface: "#151020",
  surface2: "#110D1B",
  raised: "#1C162A",
  line: "#332A45",
  lineGlow: "#726383",
  text: "#F4F0FA",
  muted: "#B9AFCB",
  dim: "#978BA9",
  chrome: "#E4DEED",
  violet: "#FF69B4",
  violet2: "#BEA0EF",
  violetDeep: "#EB53A1",
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
// Compatibility helpers keep existing semantic accents without decorative effects.
export const neonGlow = (hex: string, intensity: 1 | 2 | 3 = 2): string => {
  void hex;
  void intensity;
  return "none";
};
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
  shape: { borderRadius: 8 },
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
          minHeight: 36,
          paddingInline: 16,
          boxShadow: "none",
        },
        contained: {
          background: brand.magenta,
          color: brand.ink,
          "&:hover": { background: brand.magentaGlow, boxShadow: "none" },
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
            background: `${brand.magenta}12`,
            color: brand.text,
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
        },
      },
    },
    MuiTabs: {
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
