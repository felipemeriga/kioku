import { Box, Typography } from "@mui/material";
import { brand, fonts } from "../../theme";

export default function PillChain({
  label,
  color,
  steps,
}: {
  label: string;
  color: string;
  steps: string[];
}) {
  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        gap: 1,
        p: "14px 16px",
        borderRadius: 1,
        background: brand.surface2,
        border: `1px solid ${brand.line}`,
      }}
    >
      <Typography
        sx={{
          fontFamily: fonts.mono,
          fontSize: 11,
          letterSpacing: "0.16em",
          color,
        }}
      >
        {label}
      </Typography>
      <Box
        sx={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
          gap: "6px 4px",
        }}
      >
        {steps.map((t, i) => (
          <Box
            component="span"
            key={i}
            sx={{ display: "flex", alignItems: "center", gap: 0.5 }}
          >
            <Box
              component="span"
              sx={{
                px: "9px",
                py: "4px",
                borderRadius: 0.75,
                border: `1px solid ${color}55`,
                background: `${color}0f`,
                fontFamily: fonts.mono,
                fontSize: 12,
                color: brand.text,
                whiteSpace: "nowrap",
              }}
            >
              {t}
            </Box>
            {i < steps.length - 1 && (
              <Box
                component="span"
                sx={{ fontFamily: fonts.mono, fontSize: 12, color }}
              >
                →
              </Box>
            )}
          </Box>
        ))}
      </Box>
    </Box>
  );
}
