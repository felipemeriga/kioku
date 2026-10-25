import type { SxProps, Theme } from "@mui/material/styles";
import { brand, fonts, scanlines } from "../../theme";

export const cornerBrackets = (color: string, size = 12): SxProps<Theme> => ({
  position: "relative",
  "&::before, &::after": {
    content: '""',
    position: "absolute",
    width: `${size}px`,
    height: `${size}px`,
    pointerEvents: "none",
  },
  "&::before": {
    left: -1,
    top: -1,
    borderLeft: `2px solid ${color}`,
    borderTop: `2px solid ${color}`,
  },
  "&::after": {
    left: -1,
    bottom: -1,
    borderLeft: `2px solid ${color}`,
    borderBottom: `2px solid ${color}`,
  },
});

export const gradientRule = (color: string): SxProps<Theme> => ({
  flexGrow: 1,
  height: "1px",
  backgroundImage: `linear-gradient(90deg, ${color}66, transparent)`,
});

export const hudLabel: SxProps<Theme> = {
  fontFamily: fonts.body,
  fontSize: 13,
  fontWeight: 500,
  letterSpacing: 0,
  color: brand.muted,
  textTransform: "none",
};

export const glowText = (color: string): SxProps<Theme> => ({
  color,
});

export const scanlineOn: SxProps<Theme> = { backgroundImage: scanlines };
