import { Box, Drawer, Typography, IconButton } from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import type { IngestionStage, IngestionTask } from "../lib/api";
import PipelineBar from "./neo/PipelineBar";
import { brand, fonts, scanlines } from "../theme";

const DRAWER_WIDTH = 440;

// The 6 pipeline stage labels as shown in the mockup
const PIPELINE_NAMES = ["UPLOAD", "PARSE", "CHUNK", "META", "EMBED", "STORE"];

// Mapping from IngestionStage to the pipeline stage index (0-based, -1 = none done yet)
const STAGE_TO_IDX: Record<IngestionStage, number> = {
  uploading: 0,
  parsing: 1,
  chunking: 2,
  extracting_metadata: 3,
  embedding: 4,
  storing: 5,
  completed: 6, // all done
  error: 6, // all stages ran (to last reached)
  duplicate: 6, // all stages ran
};

function getStatusLabel(task: IngestionTask): { label: string; color: string } {
  switch (task.stage) {
    case "completed":
      return { label: "✓ Done", color: brand.green };
    case "error":
      return { label: "✕ Error", color: brand.red };
    case "duplicate":
      return { label: "⧉ Duplicate", color: brand.amber };
    case "embedding": {
      const detail = task.chunks_total
        ? `Embedding ${task.chunks_done}/${task.chunks_total}`
        : "Embedding";
      return { label: detail, color: brand.magentaGlow };
    }
    case "extracting_metadata": {
      const detail = task.chunks_total
        ? `Metadata ${task.chunks_done}/${task.chunks_total}`
        : "Metadata";
      return { label: detail, color: brand.magentaGlow };
    }
    default: {
      const names: Record<string, string> = {
        uploading: "Uploading",
        parsing: "Parsing",
        chunking: "Chunking",
        storing: "Storing",
      };
      return {
        label: task.stage_detail || names[task.stage] || task.stage,
        color: brand.magentaGlow,
      };
    }
  }
}

function buildStages(task: IngestionTask) {
  const currentIdx = STAGE_TO_IDX[task.stage];
  const isTerminal = ["completed", "error", "duplicate"].includes(task.stage);

  // Color for filled bars
  let fillColor = brand.magenta;
  if (task.stage === "completed") fillColor = brand.green;
  else if (task.stage === "error") fillColor = brand.red;
  else if (task.stage === "duplicate") fillColor = brand.amber;

  return PIPELINE_NAMES.map((name, i) => {
    if (isTerminal) {
      // All stages full
      return { label: name, pct: 100, color: fillColor };
    }
    if (i < currentIdx) {
      // Already done stages — fully filled
      return { label: name, pct: 100, color: fillColor };
    }
    if (i === currentIdx) {
      // Current active stage — partially filled (animate feel: 60%)
      return { label: name, pct: 60, color: fillColor };
    }
    // Future stages — empty
    return { label: name, pct: 0, color: fillColor };
  });
}

interface IngestionDrawerProps {
  open: boolean;
  tasks: IngestionTask[];
  onClose: () => void;
  onInteract: () => void;
}

export default function IngestionDrawer({
  open,
  tasks,
  onClose,
  onInteract,
}: IngestionDrawerProps) {
  const activeCount = tasks.filter(
    (t) => !["completed", "error", "duplicate"].includes(t.stage)
  ).length;

  return (
    <Drawer
      anchor="right"
      open={open}
      onClose={onClose}
      variant="temporary"
      onMouseEnter={onInteract}
      PaperProps={{
        sx: {
          width: DRAWER_WIDTH,
          bgcolor: brand.surface2,
          backgroundImage: scanlines,
          borderLeft: `1px solid ${brand.magenta}`,
          boxShadow: `-8px 0 32px rgba(0,0,0,0.6), 0 0 24px ${brand.magenta}33`,
        },
      }}
    >
      {/* Header */}
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1.25,
          px: 2.5,
          py: "18px",
          borderBottom: `1px solid ${brand.line}`,
        }}
      >
        <Box
          component="span"
          sx={{
            color: brand.magenta,
            textShadow: `0 0 8px ${brand.magenta}`,
            fontSize: 14,
            lineHeight: 1,
          }}
        >
          ▲
        </Box>
        <Typography
          sx={{
            fontFamily: fonts.display,
            fontSize: 17,
            fontWeight: 600,
            color: brand.text,
          }}
        >
          Processing
        </Typography>
        {activeCount > 0 && (
          <Box
            component="span"
            sx={{
              px: "8px",
              py: "2px",
              borderRadius: "3px",
              bgcolor: brand.magenta,
              color: brand.ink,
              fontFamily: fonts.mono,
              fontSize: 11,
              fontWeight: 600,
              lineHeight: "18px",
            }}
          >
            {activeCount} active
          </Box>
        )}
        <Box sx={{ flexGrow: 1 }} />
        <IconButton
          size="small"
          onClick={onClose}
          aria-label="Close"
          sx={{
            width: 32,
            height: 32,
            border: `1px solid ${brand.line}`,
            borderRadius: "3px",
            color: brand.muted,
            "&:hover": {
              borderColor: brand.magenta,
              color: brand.text,
            },
          }}
        >
          <CloseIcon sx={{ fontSize: 16 }} />
        </IconButton>
      </Box>

      {/* Task list */}
      <Box sx={{ overflow: "auto", flex: 1 }}>
        {tasks.length === 0 ? (
          <Box sx={{ p: 3, textAlign: "center" }}>
            <Typography
              sx={{ fontFamily: fonts.mono, fontSize: 13, color: brand.muted }}
            >
              No files being processed
            </Typography>
          </Box>
        ) : (
          tasks.map((task) => {
            const statusMeta = getStatusLabel(task);
            const stages = buildStages(task);
            const isError = task.stage === "error";
            const isActive = !["completed", "error", "duplicate"].includes(
              task.stage
            );

            return (
              <Box
                key={task.id}
                sx={{
                  bgcolor: isActive ? `${brand.magenta}0d` : "transparent",
                }}
              >
                <PipelineBar
                  name={task.filename}
                  status={statusMeta}
                  stages={stages}
                />
                {isError && task.error_message && (
                  <Box sx={{ px: 2, pb: 1.5, mt: -0.5 }}>
                    <Typography
                      sx={{
                        fontFamily: fonts.mono,
                        fontSize: 12,
                        color: brand.red,
                        wordBreak: "break-word",
                      }}
                    >
                      {task.error_message}
                    </Typography>
                  </Box>
                )}
              </Box>
            );
          })
        )}
      </Box>
    </Drawer>
  );
}
