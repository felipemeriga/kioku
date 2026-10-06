import { Box, Typography } from "@mui/material";
import { brand, fonts } from "../../theme";

export interface Stage {
  label: string;
  pct: number;
  color: string;
}

export default function PipelineBar({
  name,
  status,
  stages,
}: {
  name: string;
  status: { label: string; color: string };
  stages: Stage[];
}) {
  return (
    <Box sx={{ p: "12px 16px", borderBottom: `1px solid ${brand.line}` }}>
      <Box sx={{ display: "flex", alignItems: "center", mb: 1 }}>
        <Typography
          sx={{
            fontFamily: fonts.mono,
            fontSize: 13,
            color: brand.text,
            flexGrow: 1,
          }}
        >
          {name}
        </Typography>
        <Typography
          sx={{
            fontFamily: fonts.mono,
            fontSize: 12,
            color: status.color,
            textShadow: `0 0 8px ${status.color}66`,
          }}
        >
          {status.label}
        </Typography>
      </Box>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: `repeat(${stages.length}, 1fr)`,
          gap: 0.5,
        }}
      >
        {stages.map((s) => (
          <Box key={s.label}>
            <Box
              sx={{
                height: 6,
                borderRadius: 0.5,
                background: brand.line,
                overflow: "hidden",
              }}
            >
              <Box
                sx={{
                  height: "100%",
                  width: `${s.pct}%`,
                  background: s.color,
                  boxShadow:
                    s.pct > 0 && s.pct < 100 ? `0 0 8px ${s.color}` : "none",
                }}
              />
            </Box>
            <Typography
              sx={{
                fontFamily: fonts.mono,
                fontSize: 9,
                letterSpacing: "0.08em",
                color: brand.dim,
                mt: 0.5,
              }}
            >
              {s.label}
            </Typography>
          </Box>
        ))}
      </Box>
    </Box>
  );
}
