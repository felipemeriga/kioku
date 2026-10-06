import { Box, Typography } from "@mui/material";
import { Mem0BrandIcon } from "./BrandIcons";
import CornerCard from "./neo/CornerCard";
import { brand, fonts } from "../theme";

/**
 * Mem0 is self-hosted and auto-on for repo folders — there's no connect step,
 * API key, or per-folder config anymore. This section just explains that.
 */
export function Mem0IntegrationSection() {
  return (
    <CornerCard
      color="#E2B8FF"
      sx={{
        p: "22px 24px",
        display: "flex",
        flexDirection: "column",
        gap: "10px",
      }}
    >
      {/* Section heading */}
      <Box sx={{ display: "flex", alignItems: "center", gap: "10px" }}>
        <Typography
          sx={{ fontFamily: fonts.mono, fontSize: 12, color: "#E2B8FF" }}
        >
          03
        </Typography>
        <Typography sx={{ fontSize: 19, fontWeight: 600, m: 0 }}>
          Mem0 memory
        </Typography>
        <Mem0BrandIcon fontSize="small" sx={{ ml: "auto", color: "#E2B8FF" }} />
      </Box>

      <Typography
        sx={{ fontSize: 14, lineHeight: 1.6, color: brand.muted, m: 0 }}
      >
        Memory is self-hosted and{" "}
        <Box component="strong" sx={{ color: brand.text }}>
          auto-on for repo folders
        </Box>{" "}
        — no API key, no connection step. Any folder wired as a repo (via{" "}
        <Box
          component="code"
          sx={{ fontFamily: fonts.mono, color: brand.cyan }}
        >
          kioku init
        </Box>
        ) gets episodic + eternal memory automatically, scoped to that repo.
      </Typography>

      <Typography
        sx={{ fontSize: 14, lineHeight: 1.6, color: brand.muted, m: 0 }}
      >
        Agents write memories with the{" "}
        <Box
          component="code"
          sx={{ fontFamily: fonts.mono, color: brand.cyan }}
        >
          save_memory
        </Box>{" "}
        tool and read them with{" "}
        <Box
          component="code"
          sx={{ fontFamily: fonts.mono, color: brand.cyan }}
        >
          search_memory
        </Box>
        . Browse or edit a repo's memories from its folder's{" "}
        <Box component="strong" sx={{ color: brand.text }}>
          Memory
        </Box>{" "}
        tab.
      </Typography>
    </CornerCard>
  );
}
