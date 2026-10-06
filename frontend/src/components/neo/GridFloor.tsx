import { Box } from "@mui/material";
import type { SxProps, Theme } from "@mui/material/styles";
import { brand } from "../../theme";

export default function GridFloor({ sx }: { sx?: SxProps<Theme> }) {
  return (
    <Box
      aria-hidden="true"
      sx={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 0,
        height: "45%",
        overflow: "hidden",
        perspective: "320px",
        pointerEvents: "none",
        "&::before": {
          content: '""',
          position: "absolute",
          inset: "-50% -50% 0 -50%",
          backgroundImage: `linear-gradient(${brand.cyan}44 1px, transparent 1px), linear-gradient(90deg, ${brand.cyan}44 1px, transparent 1px)`,
          backgroundSize: "48px 48px",
          transform: "rotateX(72deg)",
          transformOrigin: "bottom",
          maskImage: "linear-gradient(transparent, #000 60%)",
        },
        ...sx,
      }}
    />
  );
}
