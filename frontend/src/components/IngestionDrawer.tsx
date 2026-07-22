import {
  Box,
  Drawer,
  Typography,
  IconButton,
  List,
  ListItem,
  Divider,
  alpha,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import DescriptionIcon from "@mui/icons-material/Description";
import ContentCutIcon from "@mui/icons-material/ContentCut";
import LabelIcon from "@mui/icons-material/Label";
import MemoryIcon from "@mui/icons-material/Memory";
import StorageIcon from "@mui/icons-material/Storage";
import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import ErrorIcon from "@mui/icons-material/Error";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import InsertDriveFileIcon from "@mui/icons-material/InsertDriveFile";
import type { IngestionStage, IngestionTask } from "../lib/api";

const DRAWER_WIDTH = 340;

interface StageConfig {
  label: string;
  icon: React.ReactNode;
  color: string;
}

const STAGE_CONFIGS: Record<IngestionStage, StageConfig> = {
  uploading: {
    label: "Uploading",
    icon: <CloudUploadIcon sx={{ fontSize: 16 }} />,
    color: "#FF2E93",
  },
  parsing: {
    label: "Parsing",
    icon: <DescriptionIcon sx={{ fontSize: 16 }} />,
    color: "#FF2E93",
  },
  chunking: {
    label: "Chunking",
    icon: <ContentCutIcon sx={{ fontSize: 16 }} />,
    color: "#FF2E93",
  },
  extracting_metadata: {
    label: "Metadata",
    icon: <LabelIcon sx={{ fontSize: 16 }} />,
    color: "#FF2E93",
  },
  embedding: {
    label: "Embedding",
    icon: <MemoryIcon sx={{ fontSize: 16 }} />,
    color: "#FF2E93",
  },
  storing: {
    label: "Storing",
    icon: <StorageIcon sx={{ fontSize: 16 }} />,
    color: "#FF2E93",
  },
  completed: {
    label: "Done",
    icon: <CheckCircleIcon sx={{ fontSize: 16 }} />,
    color: "#10b981",
  },
  error: {
    label: "Error",
    icon: <ErrorIcon sx={{ fontSize: 16 }} />,
    color: "#ef4444",
  },
  duplicate: {
    label: "Duplicate",
    icon: <ContentCopyIcon sx={{ fontSize: 16 }} />,
    color: "#f59e0b",
  },
};

const PIPELINE_STAGES: IngestionStage[] = [
  "uploading",
  "parsing",
  "chunking",
  "extracting_metadata",
  "embedding",
  "storing",
];

function StageIndicator({ currentStage }: { currentStage: IngestionStage }) {
  const isTerminal = ["completed", "error", "duplicate"].includes(currentStage);
  const currentIdx = isTerminal
    ? PIPELINE_STAGES.length
    : PIPELINE_STAGES.indexOf(currentStage);

  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 0.5, my: 0.5 }}>
      {PIPELINE_STAGES.map((stage, idx) => {
        const config = STAGE_CONFIGS[stage];
        const isActive = idx === currentIdx && !isTerminal;
        const isDone = idx < currentIdx || isTerminal;

        return (
          <Box
            key={stage}
            title={config.label}
            sx={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              bgcolor: isDone
                ? isTerminal
                  ? STAGE_CONFIGS[currentStage].color
                  : "#10b981"
                : isActive
                ? "#FF2E93"
                : alpha("#ffffff", 0.15),
              transition: "all 0.3s",
              ...(isActive && {
                boxShadow: `0 0 6px ${alpha("#FF2E93", 0.6)}`,
              }),
            }}
          />
        );
      })}
    </Box>
  );
}

function TaskItem({ task }: { task: IngestionTask }) {
  const config = STAGE_CONFIGS[task.stage];
  const isTerminal = ["completed", "error", "duplicate"].includes(task.stage);

  let detail = task.stage_detail || config.label;
  if (task.stage === "embedding" && task.chunks_total) {
    detail = `Embedding ${task.chunks_done}/${task.chunks_total}`;
  } else if (task.stage === "extracting_metadata" && task.chunks_total) {
    detail = `Metadata ${task.chunks_done}/${task.chunks_total}`;
  } else if (task.stage === "completed" && task.chunks_total) {
    detail = `${task.chunks_total} chunks`;
  }

  return (
    <ListItem
      sx={{
        px: 2,
        py: 1.5,
        flexDirection: "column",
        alignItems: "stretch",
        gap: 0.5,
      }}
    >
      <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
        <InsertDriveFileIcon
          sx={{ fontSize: 18, color: alpha("#ffffff", 0.35), flexShrink: 0 }}
        />
        <Typography
          variant="body2"
          noWrap
          sx={{ flex: 1, fontWeight: 500 }}
          title={task.filename}
        >
          {task.filename}
        </Typography>
      </Box>

      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          pl: 3.5,
        }}
      >
        <StageIndicator currentStage={task.stage} />
        <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
          <Box sx={{ color: config.color, display: "flex" }}>{config.icon}</Box>
          <Typography
            variant="caption"
            sx={{ color: config.color, whiteSpace: "nowrap" }}
          >
            {isTerminal ? config.label : detail}
          </Typography>
        </Box>
      </Box>

      {task.stage === "error" && task.error_message && (
        <Typography
          variant="caption"
          sx={{ color: "error.main", pl: 3.5, wordBreak: "break-word" }}
        >
          {task.error_message}
        </Typography>
      )}
    </ListItem>
  );
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
          bgcolor: alpha("#121219", 0.95),
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
          borderLeft: `1px solid ${alpha("#ffffff", 0.08)}`,
        },
      }}
    >
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          px: 2,
          py: 1.5,
          borderBottom: `1px solid ${alpha("#ffffff", 0.08)}`,
        }}
      >
        <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
          <CloudUploadIcon sx={{ color: "#FF2E93", fontSize: 20 }} />
          <Typography variant="subtitle2" sx={{ fontWeight: 600 }}>
            Processing
            {activeCount > 0 && (
              <Typography
                component="span"
                variant="caption"
                sx={{ ml: 0.5, color: "text.secondary" }}
              >
                ({activeCount} active)
              </Typography>
            )}
          </Typography>
        </Box>
        <IconButton size="small" onClick={onClose}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Box>

      <List disablePadding sx={{ overflow: "auto", flex: 1 }}>
        {tasks.length === 0 ? (
          <Box sx={{ p: 3, textAlign: "center" }}>
            <Typography variant="body2" color="text.secondary">
              No files being processed
            </Typography>
          </Box>
        ) : (
          tasks.map((task, idx) => (
            <Box key={task.id}>
              <TaskItem task={task} />
              {idx < tasks.length - 1 && (
                <Divider sx={{ borderColor: alpha("#ffffff", 0.05) }} />
              )}
            </Box>
          ))
        )}
      </List>
    </Drawer>
  );
}
