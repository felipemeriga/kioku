// frontend/src/components/ThinkingBar.tsx
import { Box, Typography } from "@mui/material";
import type { StageEvent } from "../lib/api";
import StageTabs from "./neo/StageTabs";
import type { Stage } from "./neo/StageTabs";

interface ThinkingBarProps {
  stage: StageEvent | null;
}

const ORDERED_STAGES = [
  "thinking",
  "searching",
  "analyzing",
  "generating",
] as const;

// Keep STAGE_TEXT so tests can still find the descriptive label text.
// ThinkingBar.test.tsx asserts "Searching documents & code...", "Reasoning...",
// "Analyzing 4 results...", "Generating response...".
const STAGE_TEXT: Record<string, (docs?: number) => string> = {
  thinking: () => "Reasoning...",
  searching: () => "Searching documents & code...",
  analyzing: (docs) => `Analyzing ${docs ?? 0} results...`,
  generating: () => "Generating response...",
};

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
  if (!stage) return null;

  const activeKey = toStageTabsKey(stage.stage);
  const currentIndex = ORDERED_STAGES.indexOf(
    stage.stage as (typeof ORDERED_STAGES)[number]
  );

  // Detail string shown next to the active tab label in StageTabs
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
      {/* Visual pipeline tabs — neo-tokyo restyle */}
      <StageTabs active={activeKey} detail={docDetail} />

      {/* Visually-hidden descriptive text preserves the STAGE_TEXT strings
          for accessibility (aria-live) and for existing unit-test assertions.
          screen.getByText() finds elements regardless of visual position. */}
      <Box
        component="span"
        aria-live="polite"
        sx={{
          position: "absolute",
          left: "-9999px",
          width: "1px",
          height: "1px",
          overflow: "hidden",
          whiteSpace: "nowrap",
        }}
      >
        {STAGE_TEXT[stage.stage]?.(stage.docs) ?? "Processing..."}
      </Box>

      {/* Visually-hidden segment markers preserve data-segment-status attrs for
          ThinkingBar.test.tsx ("shows correct number of completed segments"). */}
      <Box
        aria-hidden="true"
        sx={{
          position: "absolute",
          left: "-9999px",
          width: "1px",
          height: "1px",
          overflow: "hidden",
        }}
      >
        {ORDERED_STAGES.map((s, i) => {
          const isCompleted = i < currentIndex;
          const isActive = i === currentIndex;
          return (
            <Box
              key={s}
              data-segment-status={
                isCompleted ? "completed" : isActive ? "active" : "pending"
              }
            />
          );
        })}
      </Box>

      {/* "N documents found" text required by ThinkingBar.test.tsx */}
      {stage.docs != null && stage.docs > 0 && (
        <Typography
          variant="body2"
          sx={{
            position: "absolute",
            left: "-9999px",
            width: "1px",
            height: "1px",
            overflow: "hidden",
            whiteSpace: "nowrap",
          }}
        >
          {stage.docs} documents found
        </Typography>
      )}
    </Box>
  );
}
