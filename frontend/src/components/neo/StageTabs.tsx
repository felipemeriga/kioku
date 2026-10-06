import { Box, Typography } from "@mui/material";
import { brand, fonts } from "../../theme";

const STAGES = [
  { key: "thinking", jp: "思考", en: "Thinking" },
  { key: "searching", jp: "探索", en: "Searching" },
  { key: "analyzing", jp: "分析", en: "Analyzing" },
  { key: "generating", jp: "生成", en: "Generating" },
] as const;

export type Stage = (typeof STAGES)[number]["key"];

export default function StageTabs({
  active,
  detail,
}: {
  active: Stage;
  detail?: string;
}) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: "repeat(4, 1fr)",
        border: `1px solid ${brand.line}`,
        borderRadius: 1,
        overflow: "hidden",
      }}
    >
      {STAGES.map((s) => {
        const on = s.key === active;
        return (
          <Box
            key={s.key}
            sx={{
              p: "10px 14px",
              borderRight: `1px solid ${brand.line}`,
              "&:last-of-type": { borderRight: 0 },
              background: on ? `${brand.magenta}18` : "transparent",
            }}
          >
            <Typography
              sx={{
                fontFamily: fonts.jp,
                fontWeight: 700,
                fontSize: 15,
                color: on ? brand.magenta : brand.muted,
                textShadow: on ? `0 0 10px ${brand.magenta}66` : "none",
              }}
            >
              {s.jp}
            </Typography>
            <Typography
              sx={{
                fontFamily: fonts.mono,
                fontSize: 11,
                color: on ? brand.text : brand.dim,
              }}
            >
              {s.en}
              {on && detail ? ` · ${detail}` : ""}
            </Typography>
          </Box>
        );
      })}
    </Box>
  );
}
