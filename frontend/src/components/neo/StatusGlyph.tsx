import { Box } from "@mui/material";
import { STATUS_GLYPH } from "../../theme";

export type GlyphStatus = "pinned" | "hybrid" | "auto";

export default function StatusGlyph({
  status,
  size = 11,
}: {
  status: GlyphStatus;
  size?: number;
}) {
  const s = STATUS_GLYPH[status];
  return (
    <Box
      component="span"
      title={status}
      sx={{
        fontFamily: "JetBrains Mono, monospace",
        fontSize: size,
        color: s.color,
        textShadow: s.glow,
      }}
    >
      {s.glyph}
    </Box>
  );
}
