import { useState } from "react";
import {
  Box,
  Button,
  Typography,
  Collapse,
  Skeleton,
  alpha,
} from "@mui/material";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useQuery } from "@tanstack/react-query";
import { brand, fonts } from "../theme";
import { fetchDocumentation } from "../lib/api";
import { qk } from "../lib/queryKeys";

export default function DocumentationPanel({ folderId }: { folderId: string }) {
  const [expanded, setExpanded] = useState(false);
  const { data, isPending, isError } = useQuery({
    queryKey: qk.documentation(folderId),
    queryFn: () => fetchDocumentation(folderId),
  });
  const doc = data?.documentation;
  if (isPending) {
    return (
      <Box
        role="status"
        aria-label="Loading detailed documentation"
        sx={{
          border: `1px solid ${brand.line}`,
          borderRadius: "8px",
          bgcolor: brand.surface,
          mb: 3,
          ml: { xs: 0, lg: "210px" },
          p: 3,
        }}
      >
        <Skeleton variant="text" width="40%" height={30} />
        <Skeleton variant="text" width="85%" />
        <Skeleton variant="text" width="65%" />
      </Box>
    );
  }
  if (isError || !doc) return null;
  return (
    <Box
      id="briefing-documentation"
      sx={{
        border: `1px solid ${brand.line}`,
        borderRadius: "8px",
        bgcolor: brand.surface,
        mb: 3,
        ml: { xs: 0, lg: "210px" },
        overflow: "hidden",
        scrollMarginTop: 24,
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
      <Box sx={{ p: { xs: 2, md: 3 } }}>
        <Typography
          sx={{
            color: brand.text,
            fontSize: 16,
            lineHeight: 1.75,
            maxWidth: "78ch",
            ...(!expanded && {
              display: "-webkit-box",
              WebkitBoxOrient: "vertical",
              WebkitLineClamp: 3,
              overflow: "hidden",
            }),
          }}
        >
          {doc.abstract || "Generated repository documentation."}
        </Typography>
        <Collapse in={expanded}>
          <Box
            sx={{
              pt: 3,
              maxWidth: "78ch",
              fontSize: 16,
              lineHeight: 1.8,
              overflowWrap: "anywhere",
              "& h1, & h2, & h3": {
                color: brand.text,
                lineHeight: 1.35,
                mt: 4,
                mb: 1.5,
              },
              "& h1": { fontSize: "1.5rem" },
              "& h2": {
                fontSize: "1.2rem",
                borderLeft: `2px solid ${brand.magenta}`,
                bgcolor: alpha(brand.magenta, 0.06),
                px: 1.75,
                py: 1,
              },
              "& h3": { fontSize: "1.05rem" },
              "& p": { my: 1.5 },
              "& ul, & ol": { pl: 3, my: 1.5 },
              "& li": { mb: 0.5 },
              "& pre": {
                overflow: "auto",
                p: 2,
                bgcolor: brand.ink,
                border: `1px solid ${brand.line}`,
                borderRadius: 1,
              },
              "& :not(pre) > code": {
                fontFamily: fonts.mono,
                fontSize: "0.86em",
                color: brand.cyan,
                bgcolor: alpha(brand.cyan, 0.15),
                boxShadow: `inset 0 -1px 0 ${alpha(brand.cyan, 0.55)}`,
                px: 0.35,
                py: 0.1,
                borderRadius: 0.5,
              },
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
