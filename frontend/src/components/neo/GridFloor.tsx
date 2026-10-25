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
        left: 0,
        right: 0,
        bottom: 0,
        height: "40%",
        overflow: "hidden",
        pointerEvents: "none",
        ...sx,
      }}
    >
      <Box
        sx={{
          position: "absolute",
          inset: 0,
          transform: "perspective(360px) rotateX(62deg)",
          transformOrigin: "top center",
        }}
      >
        <Box
          data-testid="retro-grid"
          sx={{
            position: "absolute",
            inset: "-48px -40% 0",
            backgroundImage: `linear-gradient(${brand.cyan}66 1px, transparent 1px), linear-gradient(90deg, ${brand.cyan}66 1px, transparent 1px)`,
            backgroundSize: "64px 48px",
            ...(animate
              ? {
                  "@keyframes gridScroll": {
                    from: { transform: "translate3d(0,-48px,0)" },
                    to: { transform: "translate3d(0,0,0)" },
                  },
                  animation: "gridScroll 8s linear infinite",
                  "@media (prefers-reduced-motion: reduce)": {
                    animation: "none",
                  },
                }
              : {}),
          }}
        />
      </Box>
    </Box>
  );
}
