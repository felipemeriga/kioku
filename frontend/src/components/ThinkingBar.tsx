// frontend/src/components/ThinkingBar.tsx
import { useEffect, useState } from "react";
import { Box, Typography } from "@mui/material";
import type { StageEvent } from "../lib/api";
import { brand, fonts } from "../theme";
import StageTabs from "./neo/StageTabs";
import type { Stage } from "./neo/StageTabs";

interface ThinkingBarProps {
  stage: StageEvent | null;
}

// Map StageEvent.stage values to the StageTabs Stage union type.
// Unknown stages fall back to "thinking" as a safe default.
const toStageTabsKey = (s: string): Stage => {
  if (
    s === "thinking" ||
    s === "searching" ||
    s === "analyzing" ||
    s === "generating"
  ) {
    return s;
  }
  return "thinking";
};

export default function ThinkingBar({ stage }: ThinkingBarProps) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const timer = window.setInterval(() => {
      setElapsed(Math.floor((Date.now() - started) / 1000));
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  if (!stage) return null;

  const activeKey = toStageTabsKey(stage.stage);
  // Detail string shown next to the active tab label in StageTabs.
  const docDetail =
    stage.docs != null && stage.docs > 0 ? `${stage.docs} docs` : undefined;

  return (
    <Box
      data-testid="thinking-bar"
      sx={{
        mb: 2,
        animation: "fadeSlideIn 0.2s ease-out",
        "@keyframes fadeSlideIn": {
          from: { opacity: 0, transform: "translateY(4px)" },
          to: { opacity: 1, transform: "translateY(0)" },
        },
      }}
    >
      <StageTabs active={activeKey} detail={docDetail} />
      <Typography
        role="status"
        aria-live="polite"
        sx={{ mt: 1, fontFamily: fonts.body, fontSize: 13, color: brand.muted }}
      >
        {stage.detail ?? "Working on your answer"} · {Math.floor(elapsed / 60)}:
        {String(elapsed % 60).padStart(2, "0")}
      </Typography>
    </Box>
  );
}
