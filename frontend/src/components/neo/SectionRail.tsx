import { Box, Stack, Typography } from "@mui/material";
import { brand, fonts } from "../../theme";
import { hudLabel } from "./sx";
import StatusGlyph, { type GlyphStatus } from "./StatusGlyph";

export interface RailItem {
  n: string;
  title: string;
  status: GlyphStatus;
}

export default function SectionRail({
  items,
  activeIndex,
  onSelect,
}: {
  items: RailItem[];
  activeIndex: number;
  onSelect: (i: number) => void;
}) {
  return (
    <Box
      component="aside"
      aria-label="Briefing sections"
      sx={{
        width: 210,
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
        gap: 0.5,
      }}
    >
      <Typography sx={{ ...hudLabel, px: 1.25, pb: 1.25, fontSize: 10 }}>
        SECTIONS
      </Typography>
      {items.map((s, i) => (
        <Box
          key={s.n}
          component="button"
          onClick={() => onSelect(i)}
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 1,
            px: 1.25,
            py: 1,
            borderRadius: 0.75,
            border: 0,
            cursor: "pointer",
            textAlign: "left",
            fontSize: 14,
            fontFamily: fonts.body,
            background:
              i === activeIndex ? `${brand.magenta}22` : "transparent",
            boxShadow:
              i === activeIndex ? `inset 2px 0 0 ${brand.magenta}` : "none",
            color: i === activeIndex ? brand.text : "#CFC6E6",
            fontWeight: i === activeIndex ? 600 : 400,
          }}
        >
          <Box
            component="span"
            sx={{
              width: 18,
              fontFamily: fonts.mono,
              fontSize: 11,
              color: brand.muted,
            }}
          >
            {s.n}
          </Box>
          <Box component="span" sx={{ flexGrow: 1 }}>
            {s.title}
          </Box>
          <StatusGlyph status={s.status} />
        </Box>
      ))}
      <Stack
        sx={{
          gap: 0.75,
          mt: 2,
          pt: 1.5,
          px: 1.25,
          borderTop: `1px solid ${brand.line}`,
          fontFamily: fonts.mono,
          fontSize: 11,
          color: brand.muted,
        }}
      >
        <span>
          <Box component="span" sx={{ color: brand.magenta }}>
            ●
          </Box>{" "}
          pinned
        </span>
        <span>
          <Box component="span" sx={{ color: brand.cyan }}>
            ◐
          </Box>{" "}
          hybrid
        </span>
        <span>
          <Box component="span" sx={{ color: brand.muted }}>
            ○
          </Box>{" "}
          auto
        </span>
      </Stack>
    </Box>
  );
}
