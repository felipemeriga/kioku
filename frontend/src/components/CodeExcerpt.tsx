import { useEffect, useState } from "react";
import type { ComponentType, CSSProperties } from "react";
import { Box } from "@mui/material";
import type { SyntaxHighlighterProps } from "react-syntax-highlighter";
import { brand, fonts } from "../theme";

import { codeLanguage } from "./codeLanguage";

/** Render retrieved bytes as code; never reconstruct missing formatting. */
export default function CodeExcerpt({
  code,
  filename = "",
  language: requestedLanguage,
  compact = true,
  testId,
}: {
  code: string;
  filename?: string;
  language?: string;
  compact?: boolean;
  testId: string;
}) {
  const [highlighter, setHighlighter] = useState<{
    Component: ComponentType<SyntaxHighlighterProps>;
    theme: Record<string, CSSProperties>;
  } | null>(null);
  const language = requestedLanguage ?? codeLanguage(filename);
  const canHighlight = Boolean(
    language && language !== "text" && code.length <= 120_000,
  );
  useEffect(() => {
    if (!canHighlight) return;
    let active = true;
    void Promise.all([
      import("react-syntax-highlighter"),
      import("react-syntax-highlighter/dist/esm/styles/prism/one-dark"),
    ])
      .then(([module, theme]) => {
        if (active)
          setHighlighter({
            Component: module.PrismAsync,
            theme: theme.default,
          });
      })
      .catch(() => {
        /* The plain preformatted block remains readable offline. */
      });
    return () => {
      active = false;
    };
  }, [canHighlight]);
  const style: CSSProperties = {
    margin: 0,
    padding: "10px",
    background: "transparent",
    fontFamily: fonts.mono,
    fontSize: 12,
    lineHeight: 1.6,
    whiteSpace: "pre-wrap",
    overflowWrap: "anywhere",
  };
  return (
    <Box
      data-testid={testId}
      data-language={language ?? "text"}
      sx={{
        mt: 1,
        maxHeight: compact ? 180 : 480,
        overflow: compact ? "hidden" : "auto",
        bgcolor: brand.surface2,
        border: `1px solid ${brand.line}`,
        borderRadius: 1,
      }}
    >
      {highlighter && canHighlight ? (
        <highlighter.Component
          language={language}
          style={highlighter.theme}
          customStyle={style}
          codeTagProps={{ style: { fontFamily: fonts.mono } }}
          wrapLongLines
        >
          {code}
        </highlighter.Component>
      ) : (
        <pre style={style}>
          <code>{code}</code>
        </pre>
      )}
    </Box>
  );
}
