import { useState } from "react";
import { Box, Button, Chip } from "@mui/material";
import CodeExcerpt from "./CodeExcerpt";
import { codeLanguage } from "./codeLanguage";
import { brand } from "../theme";
import CodeIcon from "@mui/icons-material/Code";
import SettingsIcon from "@mui/icons-material/Settings";
import DataObjectIcon from "@mui/icons-material/DataObject";

const supportedSyntax = new Set([
  "json",
  "yaml",
  "toml",
  "rust",
  "python",
  "typescript",
  "javascript",
  "tsx",
  "jsx",
  "go",
  "java",
  "c",
  "cpp",
  "csharp",
  "sql",
  "bash",
  "powershell",
  "ruby",
  "protobuf",
  "markup",
  "css",
  "scss",
  "markdown",
  "text",
]);

function displayCode(text: string, filename?: string, language?: string) {
  let syntax = language ?? codeLanguage(filename ?? "");
  let code = text;
  const fence = text.trim().match(/^```([\w+-]+)\s*\n([\s\S]*?)\n```$/);
  if (fence && !syntax) {
    const declared = fence[1].toLowerCase();
    const alias =
      (
        {
          yml: "yaml",
          js: "javascript",
          ts: "typescript",
          rs: "rust",
          html: "markup",
        } as Record<string, string>
      )[declared] ?? declared;
    syntax = supportedSyntax.has(alias) ? alias : "text";
    code = fence[2];
  }
  if (syntax === "json" || (!syntax && /^[\s]*[[{]/.test(code))) {
    try {
      code = JSON.stringify(JSON.parse(code), null, 2);
      syntax = "json";
    } catch {
      /* Incomplete JSON stays intact and readable. */
    }
  }
  // Assignment syntax occurs in many languages; only infer configuration from
  // a whole simple configuration block, never from aggregated source excerpts.
  const lines = code
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  if (
    !syntax &&
    lines.length &&
    lines.every(
      (line) =>
        /^#/.test(line) ||
        /^\[\[?[\w."'-]+\]\]?$/.test(line) ||
        /^[\w.-]+\s*=\s*(?:["'\d[{]|true\b|false\b)/.test(line),
    )
  )
    syntax = "toml";
  if (!syntax && /^\s*[\w.-]+:\s*(?:\S|$)/m.test(code)) syntax = "yaml";
  return { code, syntax: syntax ?? "text" };
}

/** Presentation formatting never replaces the original evidence. */
export default function InspectCode({
  children,
  filename,
  language,
}: {
  children: string;
  filename?: string;
  language?: string;
}) {
  const [raw, setRaw] = useState(false);
  const display = displayCode(children, filename, language);
  return (
    <Box data-testid="inspect-code">
      {display.syntax !== "text" && (
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <Chip
            size="small"
            variant="outlined"
            icon={
              display.syntax === "json" ? (
                <DataObjectIcon />
              ) : ["yaml", "toml"].includes(display.syntax) ? (
                <SettingsIcon />
              ) : (
                <CodeIcon />
              )
            }
            label={
              (
                {
                  protobuf: "Proto",
                  javascript: "JS",
                  typescript: "TS",
                  json: "JSON",
                  yaml: "YAML",
                  toml: "TOML",
                  cpp: "C++",
                  csharp: "C#",
                } as Record<string, string>
              )[display.syntax] ??
              display.syntax.charAt(0).toUpperCase() + display.syntax.slice(1)
            }
            sx={{
              color: brand.muted,
              height: 24,
              "& .MuiChip-icon": { color: brand.cyan, fontSize: 16 },
            }}
          />
          <Button
            size="small"
            aria-label={raw ? "Show formatted text" : "Show raw text"}
            onClick={() => setRaw(!raw)}
          >
            {raw ? "Formatted" : "Raw"}
          </Button>
        </Box>
      )}
      <CodeExcerpt
        code={raw ? children : display.code}
        language={raw ? "text" : display.syntax}
        compact={false}
        testId="inspect-code-content"
      />
    </Box>
  );
}
