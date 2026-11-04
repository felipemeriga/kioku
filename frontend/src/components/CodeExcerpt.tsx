import { useEffect, useState } from "react";
import type { ComponentType, CSSProperties } from "react";
import { Box } from "@mui/material";
import type { SyntaxHighlighterProps } from "react-syntax-highlighter";
import { brand, fonts } from "../theme";

const languages: Record<string, string> = {
  rs: "rust",
  py: "python",
  ts: "typescript",
  tsx: "tsx",
  js: "javascript",
  jsx: "jsx",
  go: "go",
  java: "java",
  c: "c",
  h: "c",
  cpp: "cpp",
  cc: "cpp",
  cs: "csharp",
  json: "json",
  yml: "yaml",
  yaml: "yaml",
  toml: "toml",
  sql: "sql",
  sh: "bash",
  bash: "bash",
  ps1: "powershell",
  rb: "ruby",
  proto: "protobuf",
  xml: "markup",
};

/** Render retrieved bytes as code; never reconstruct missing formatting. */
export default function CodeExcerpt({
  code,
  filename,
  testId,
}: {
  code: string;
  filename: string;
  testId: string;
}) {
  const [highlighter, setHighlighter] = useState<{
    Component: ComponentType<SyntaxHighlighterProps>;
    theme: Record<string, CSSProperties>;
  } | null>(null);
  useEffect(() => {
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
  }, []);
  const extension = filename.split(".").pop()?.toLowerCase() ?? "";
  const language = languages[extension];
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
        maxHeight: 180,
        overflow: "hidden",
        bgcolor: brand.surface2,
        border: `1px solid ${brand.line}`,
        borderRadius: 1,
      }}
    >
      {highlighter && language ? (
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
