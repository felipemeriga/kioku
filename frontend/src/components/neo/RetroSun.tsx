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
      data-testid="retro-sun"
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
        // Animate opacity only; the gradient and glow are painted once.
        "@keyframes sunPulse": {
          "0%, 100%": { opacity: 0.65 },
          "50%": { opacity: 0.9 },
        },
        animation: "sunPulse 8s ease-in-out infinite",
        "@media (prefers-reduced-motion: reduce)": {
          animation: "none",
          opacity: 0.8,
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
            top: `${(bar.top / 260) * 100}%`,
            height: `${(bar.height / 260) * 100}%`,
            background: "#1A0630",
            pointerEvents: "none",
          }}
        />
      ))}
    </Box>
  );
}
