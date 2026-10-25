import { Box } from "@mui/material";
import { brand, fonts } from "../../theme";
import GridFloor from "./GridFloor";
import RetroSun from "./RetroSun";

/** The original retrowave scene, kept behind content and faded inside the workspace. */
export default function NeoAtmosphere({ login = false }: { login?: boolean }) {
  return (
    <Box
      aria-hidden="true"
      data-testid={login ? "login-atmosphere" : "app-atmosphere"}
      sx={{
        position: "absolute",
        inset: 0,
        overflow: "hidden",
        pointerEvents: "none",
        zIndex: -1,
        opacity: login ? 1 : 0.16,
        background: login
          ? "linear-gradient(180deg, #070310 0%, #250A3F 62%, #080410 62.1%)"
          : undefined,
      }}
    >
      <RetroSun
        sx={{
          left: login ? { xs: "50%", md: "26%" } : "80%",
          bottom: login ? { xs: "61%", md: "38%" } : "22%",
          transform: "translateX(-50%)",
          width: login ? { xs: 290, md: 410 } : 320,
          height: login ? { xs: 210, md: 290 } : 230,
          borderRadius: "220px 220px 0 0",
        }}
      />
      <GridFloor animate sx={{ height: login ? "38%" : "22%" }} />
      <Box
        sx={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: login ? "38%" : "22%",
          height: 2,
          bgcolor: brand.magenta,
          boxShadow: `0 0 14px ${brand.magenta}`,
        }}
      />
      {login && (
        <Box
          sx={{
            position: "absolute",
            left: { xs: 18, md: "10%" },
            top: { xs: 28, md: "16%" },
            writingMode: "vertical-rl",
            fontFamily: fonts.jp,
            fontSize: { xs: 42, md: 78 },
            lineHeight: 1.2,
            color: brand.text,
            textShadow: `0 0 12px ${brand.magenta}, 0 0 30px ${brand.magenta}88`,
            opacity: { xs: 0.7, md: 0.95 },
          }}
        >
          記憶
        </Box>
      )}
    </Box>
  );
}
