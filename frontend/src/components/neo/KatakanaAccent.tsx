import { Box } from "@mui/material";
import type { SxProps, Theme } from "@mui/material/styles";
import { brand, fonts } from "../../theme";

export default function KatakanaAccent({
  text,
  sx,
}: {
  text: string;
  sx?: SxProps<Theme>;
}) {
  return (
    <Box
      aria-hidden="true"
      sx={{
        position: "absolute",
        fontFamily: fonts.jp,
        fontWeight: 900,
        lineHeight: 1,
        color: "transparent",
        WebkitTextStroke: `1px ${brand.magenta}33`,
        userSelect: "none",
        pointerEvents: "none",
        ...sx,
      }}
    >
      {text}
    </Box>
  );
}
