import { Box, Typography } from "@mui/material";
import { brand, fonts } from "../../theme";

export default function RerankBar({
  file,
  score,
}: {
  file: string;
  score: number;
}) {
  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 1 }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
        <Box
          component="span"
          sx={{
            px: 0.75,
            py: 0.25,
            borderRadius: 0.5,
            border: `1px solid ${brand.line}`,
            fontFamily: fonts.mono,
            fontSize: 10,
            color: "#93c5fd",
          }}
        >
          doc
        </Box>
        <Typography
          sx={{
            fontFamily: fonts.mono,
            fontSize: 13,
            color: brand.text,
            flexGrow: 1,
          }}
        >
          {file}
        </Typography>
        <Typography
          sx={{ fontFamily: fonts.mono, fontSize: 12, color: brand.muted }}
        >
          rerank{" "}
          <Box
            component="span"
            sx={{
              color: brand.magentaGlow,
              textShadow: `0 0 8px ${brand.magenta}88`,
            }}
          >
            {score.toFixed(3)}
          </Box>
        </Typography>
      </Box>
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
            width: `${Math.round(score * 100)}%`,
            backgroundImage: `linear-gradient(90deg, ${brand.magentaDeep}, ${brand.magenta})`,
            boxShadow: `0 0 8px ${brand.magenta}`,
          }}
        />
      </Box>
    </Box>
  );
}
