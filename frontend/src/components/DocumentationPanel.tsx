import { useState } from "react";
import { Box, Button, Typography, Collapse } from "@mui/material";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useQuery } from "@tanstack/react-query";
import { brand } from "../theme";
import { fetchDocumentation } from "../lib/api";
import { qk } from "../lib/queryKeys";

export default function DocumentationPanel({ folderId }: { folderId: string }) {
  const [expanded, setExpanded] = useState(false);
  const { data, isPending, isError } = useQuery({
    queryKey: qk.documentation(folderId),
    queryFn: () => fetchDocumentation(folderId),
  });
  const doc = data?.documentation;
  if (isPending || isError || !doc) return null;
  return (
    <Box
      sx={{
        border: `1px solid ${brand.line}`,
        borderRadius: "8px",
        bgcolor: brand.surface,
        mb: 3,
        overflow: "hidden",
      }}
    >
      <Box
        sx={{
          px: 3,
          py: 2.5,
          borderBottom: `1px solid ${brand.line}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 2,
          flexWrap: "wrap",
        }}
      >
        <Box>
          <Typography component="h2" sx={{ fontSize: 20, fontWeight: 600 }}>
            Detailed documentation
          </Typography>
          <Typography sx={{ fontSize: 13, color: brand.muted, mt: 0.5 }}>
            Generated {new Date(doc.generated_at).toLocaleString()}
          </Typography>
        </Box>
        <Button
          variant="outlined"
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
        >
          {expanded ? "Close documentation" : "Read documentation"}
        </Button>
      </Box>
      <Box sx={{ p: 3 }}>
        <Typography sx={{ color: brand.muted, fontSize: 16, lineHeight: 1.75 }}>
          {doc.abstract || "Generated repository documentation."}
        </Typography>
        <Collapse in={expanded}>
          <Box
            sx={{
              pt: 3,
              fontSize: 16,
              lineHeight: 1.75,
              overflowWrap: "anywhere",
              "& pre": { overflow: "auto", p: 2, bgcolor: brand.ink },
              "& table": {
                display: "block",
                overflow: "auto",
                borderCollapse: "collapse",
              },
              "& td, & th": { border: `1px solid ${brand.line}`, p: 1 },
            }}
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {doc.content}
            </ReactMarkdown>
          </Box>
        </Collapse>
      </Box>
    </Box>
  );
}
