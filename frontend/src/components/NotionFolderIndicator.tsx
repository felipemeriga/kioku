import { useQuery } from "@tanstack/react-query";
import { Box, Tooltip } from "@mui/material";
import { Link } from "react-router-dom";
import { fetchNotionConfigs, fetchActiveIngestionJobs } from "../lib/api";
import { qk } from "../lib/queryKeys";

/** Only an exact sync target gets a badge; all instances share cached reads. */
export default function NotionFolderIndicator({
  folderId,
}: {
  folderId: string;
}) {
  const { data: configs } = useQuery({
    queryKey: qk.notionConfigs(),
    queryFn: fetchNotionConfigs,
    staleTime: 30000,
    refetchInterval: 30000,
  });
  const config = configs?.find((item) => item.root_folder_id === folderId);
  const { data: jobs } = useQuery({
    queryKey: ["notion-active-jobs"],
    queryFn: fetchActiveIngestionJobs,
    enabled: !!config,
    staleTime: 15000,
    refetchInterval: 15000,
  });
  if (!config) return null;
  const running = jobs?.some(
    (job) =>
      job.kind === "notion_sync" &&
      job.root_folder_id === folderId &&
      ["queued", "running"].includes(job.status)
  );
  const last = config.last_fast_sync_at || config.last_full_sync_at;
  const status = running
    ? "Sync in progress"
    : config.last_error
    ? `Sync needs attention: ${config.last_error}`
    : last
    ? `Last synced ${new Date(last).toLocaleString()}`
    : "Not synced yet";
  return (
    <Tooltip
      title={
        <Box sx={{ whiteSpace: "normal", overflowWrap: "anywhere" }}>
          Notion · {status}
          <br />
          Manage in Settings → Integrations
        </Box>
      }
    >
      <Box
        component={Link}
        to="/settings?tab=integrations"
        aria-label={`Notion sync: ${status}. Manage integration`}
        data-testid={`notion-folder-${folderId}`}
        onClick={(event) => event.stopPropagation()}
        onKeyDown={(event) => event.stopPropagation()}
        sx={{
          display: "inline-flex",
          alignItems: "center",
          justifyContent: "center",
          width: 24,
          height: 24,
          flexShrink: 0,
          ml: 0.75,
          verticalAlign: "middle",
          color: "#fff",
          "&:focus-visible": { outline: "2px solid #00F0FF" },
        }}
      >
        <Box component="img" src="/notion.svg" alt="" width={18} height={18} />
      </Box>
    </Tooltip>
  );
}
