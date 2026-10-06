import { Box } from "@mui/material";
import type { SxProps, Theme } from "@mui/material/styles";
import { brand } from "../../theme";

/**
 * Retrowave sun: semicircle with sunset gradient + horizontal slit bars + glow.
 * Presentational only — aria-hidden, pointer-events: none.
 */
export default function RetroSun({ sx }: { sx?: SxProps<Theme> }) {
  const slitBars: Array<{ top: number; height: number }> = [
    { top: 140, height: 6 },
    { top: 170, height: 9 },
    { top: 200, height: 12 },
    { top: 230, height: 16 },
  ];

  return (
    <Box
      aria-hidden="true"
      sx={{
        position: "absolute",
        width: 360,
        height: 260,
        borderRadius: "180px 180px 0 0",
        overflow: "hidden",
        backgroundImage: `linear-gradient(180deg, ${brand.amber} 0%, ${brand.magenta} 55%, ${brand.purple} 100%)`,
        opacity: 0.55,
        boxShadow: `0 0 80px ${brand.magenta}55`,
        pointerEvents: "none",
        // Slow glow/opacity pulse — breathe over 6s
        "@keyframes sunPulse": {
          "0%": {
            opacity: 0.45,
            boxShadow: `0 0 60px ${brand.magenta}33`,
          },
          "50%": {
            opacity: 0.65,
            boxShadow: `0 0 100px ${brand.magenta}77`,
          },
          "100%": {
            opacity: 0.45,
            boxShadow: `0 0 60px ${brand.magenta}33`,
          },
        },
        animation: "sunPulse 6s ease-in-out infinite",
        "@media (prefers-reduced-motion: reduce)": {
          animation: "none",
          opacity: 0.55,
          boxShadow: `0 0 80px ${brand.magenta}55`,
        },
        ...sx,
      }}
    >
      {slitBars.map((bar) => (
        <Box
          key={bar.top}
          sx={{
            position: "absolute",
            left: 0,
            right: 0,
            top: bar.top,
            height: bar.height,
            background: "#1A0630",
            pointerEvents: "none",
          }}
        />
      ))}
    </Box>
  );
}
