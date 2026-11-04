import { useState } from "react";
import { Box, Button, Typography } from "@mui/material";
import type { DebugToolCall } from "../lib/api";
import { brand } from "../theme";
import InspectCode from "./InspectCode";

export default function InspectScope({
  scope,
}: {
  scope: NonNullable<DebugToolCall["effective_scope"]>;
}) {
  const [foldersOpen, setFoldersOpen] = useState(false);
  const [technicalOpen, setTechnicalOpen] = useState(false);
  const folders = [...new Set(scope.folder_ids)];
  return (
    <Box sx={{ mt: 1, mb: 2 }}>
      <Typography sx={{ fontSize: 13, fontWeight: 600 }}>
        Search scope
      </Typography>
      <Typography sx={{ color: brand.muted, fontSize: 13 }}>
        {folders.length} eligible {folders.length === 1 ? "folder" : "folders"}{" "}
        · {scope.filename ? `File: ${scope.filename}` : "All filenames"}
      </Typography>
      <Typography sx={{ color: brand.muted, fontSize: 12 }}>
        Locations available to this search. Returned evidence appears below and
        in Chunks.
      </Typography>
      <Button
        size="small"
        onClick={() => setFoldersOpen(!foldersOpen)}
        aria-expanded={foldersOpen}
      >
        {foldersOpen ? "Hide folders" : "View folders"}
      </Button>
      <Button
        size="small"
        onClick={() => setTechnicalOpen(!technicalOpen)}
        aria-expanded={technicalOpen}
      >
        {technicalOpen ? "Hide technical details" : "Technical details"}
      </Button>
      {foldersOpen && (
        <Box
          component="ul"
          sx={{ my: 1, pl: 3, maxHeight: 180, overflow: "auto" }}
        >
          {folders.map((id) => (
            <Typography
              component="li"
              key={id}
              sx={{ color: brand.muted, fontSize: 13 }}
            >
              {scope.breadcrumbs?.[id]?.join(" / ") ||
                "Folder name unavailable"}
            </Typography>
          ))}
        </Box>
      )}
      {technicalOpen && (
        <InspectCode language="json">
          {JSON.stringify(scope, null, 2)}
        </InspectCode>
      )}
    </Box>
  );
}
