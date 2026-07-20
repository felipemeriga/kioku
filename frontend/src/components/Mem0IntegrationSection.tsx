import { Card, CardContent, Stack, Typography } from "@mui/material";
import { Mem0BrandIcon } from "./BrandIcons";

/**
 * Mem0 is self-hosted and auto-on for repo folders — there's no connect step,
 * API key, or per-folder config anymore. This section just explains that.
 */
export function Mem0IntegrationSection() {
  return (
    <Card sx={{ mb: 3 }}>
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1.5} sx={{ mb: 1 }}>
          <Mem0BrandIcon fontSize="small" />
          <Typography variant="h6">Mem0 memory</Typography>
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          Memory is self-hosted and <b>auto-on for repo folders</b> — no API
          key, no connection step. Any folder wired as a repo (via{" "}
          <code>kioku init</code>) gets episodic + eternal memory automatically,
          scoped to that repo.
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Agents write memories with the <code>save_memory</code> tool and read
          them with <code>search_memory</code>. Browse or edit a repo's memories
          from its folder's <b>Memory</b> tab.
        </Typography>
      </CardContent>
    </Card>
  );
}
