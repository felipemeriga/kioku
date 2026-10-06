import { Box } from "@mui/material";
import type { SxProps, Theme } from "@mui/material/styles";
import { brand } from "../../theme";

interface GridFloorProps {
  animate?: boolean;
  sx?: SxProps<Theme>;
}

export default function GridFloor({ animate = false, sx }: GridFloorProps) {
  return (
    <Box
      aria-hidden="true"
      sx={{
        position: "absolute",
        left: "-400px",
        right: "-400px",
        bottom: 0,
        height: "40%",
        overflow: "hidden",
        pointerEvents: "none",
        // Grid inner element uses the perspective + rotateX approach from mockup
        "&::before": {
          content: '""',
          position: "absolute",
          inset: 0,
          backgroundColor: "#08040F",
          backgroundImage: `linear-gradient(${brand.cyan}55 1.5px, transparent 1.5px), linear-gradient(90deg, ${brand.cyan}55 1.5px, transparent 1.5px)`,
          backgroundSize: "64px 48px",
          transform: "perspective(360px) rotateX(62deg)",
          transformOrigin: "top center",
          // Animated grid scroll — slowly moves toward horizon
          ...(animate
            ? {
                "@keyframes gridScroll": {
                  "0%": { backgroundPosition: "0px 0px" },
                  "100%": { backgroundPosition: "0px 48px" },
                },
                animation: "gridScroll 8s linear infinite",
                "@media (prefers-reduced-motion: reduce)": {
                  animation: "none",
                },
              }
            : {}),
        },
        ...sx,
      }}
    />
  );
}
