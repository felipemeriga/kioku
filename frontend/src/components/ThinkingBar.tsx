// frontend/src/components/ThinkingBar.tsx
import { Box, Typography, alpha } from "@mui/material";
import type { StageEvent } from "../lib/api";

interface ThinkingBarProps {
  stage: StageEvent | null;
}

const STAGES = ["searching", "analyzing", "generating"] as const;

const STAGE_TEXT: Record<string, (docs?: number) => string> = {
  searching: () => "Searching documents...",
  analyzing: (docs) => `Analyzing ${docs ?? 0} results...`,
  generating: () => "Generating response...",
};

export default function ThinkingBar({ stage }: ThinkingBarProps) {
  if (!stage) return null;

  const currentIndex = STAGES.indexOf(stage.stage);

  return (
    <Box
      data-testid="thinking-bar"
      sx={{
        display: "flex",
        alignItems: "center",
        gap: 1.5,
        px: 2,
        py: 1.25,
        mb: 2,
        bgcolor: alpha("#FF2E93", 0.08),
        border: 1,
        borderColor: alpha("#FF2E93", 0.2),
        borderRadius: 2.5,
        animation: "fadeSlideIn 0.2s ease-out",
        "@keyframes fadeSlideIn": {
          from: { opacity: 0, transform: "translateY(4px)" },
          to: { opacity: 1, transform: "translateY(0)" },
        },
      }}
    >
      {/* Segmented progress */}
      <Box sx={{ display: "flex", gap: 0.5 }}>
        {STAGES.map((s, i) => {
          const isCompleted = i < currentIndex;
          const isActive = i === currentIndex;
          return (
            <Box
              key={s}
              data-segment-status={
                isCompleted ? "completed" : isActive ? "active" : "pending"
              }
              sx={{
                width: 20,
                height: 3,
                borderRadius: 1,
                bgcolor: isCompleted
                  ? "#10b981"
                  : isActive
                    ? "#FF2E93"
                    : alpha("#ffffff", 0.1),
                ...(isActive && {
                  animation: "pulse 1.5s infinite",
                  "@keyframes pulse": {
                    "0%, 100%": { opacity: 1 },
                    "50%": { opacity: 0.4 },
                  },
                }),
              }}
            />
          );
        })}
      </Box>

      {/* Stage text */}
      <Typography
        variant="body2"
        sx={{
          color: "#a78bfa",
          fontSize: 12,
          fontWeight: 500,
        }}
      >
        {STAGE_TEXT[stage.stage]?.(stage.docs) ?? "Processing..."}
      </Typography>

      {/* Context info */}
      {stage.docs != null && stage.docs > 0 && (
        <Typography
          variant="body2"
          sx={{
            color: alpha("#ffffff", 0.3),
            fontSize: 11,
            ml: "auto",
          }}
        >
          {stage.docs} documents found
        </Typography>
      )}
    </Box>
  );
}
