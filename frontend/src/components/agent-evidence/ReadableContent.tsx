import { useState } from "react";
import { IconButton, Tooltip } from "@mui/material";
import WrapTextIcon from "@mui/icons-material/WrapText";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import SyntaxHighlighter from "react-syntax-highlighter/dist/esm/prism-light";
import bash from "react-syntax-highlighter/dist/esm/languages/prism/bash";
import rust from "react-syntax-highlighter/dist/esm/languages/prism/rust";
import javascript from "react-syntax-highlighter/dist/esm/languages/prism/javascript";
import typescript from "react-syntax-highlighter/dist/esm/languages/prism/typescript";
import json from "react-syntax-highlighter/dist/esm/languages/prism/json";
import python from "react-syntax-highlighter/dist/esm/languages/prism/python";
import go from "react-syntax-highlighter/dist/esm/languages/prism/go";
import yaml from "react-syntax-highlighter/dist/esm/languages/prism/yaml";
import sql from "react-syntax-highlighter/dist/esm/languages/prism/sql";
import c from "react-syntax-highlighter/dist/esm/languages/prism/c";
import cpp from "react-syntax-highlighter/dist/esm/languages/prism/cpp";
import markup from "react-syntax-highlighter/dist/esm/languages/prism/markup";
import css from "react-syntax-highlighter/dist/esm/languages/prism/css";
import toml from "react-syntax-highlighter/dist/esm/languages/prism/toml";
import {
  readableBlocks,
  readableLanguage,
  type ReadableKind,
} from "./contentBlocks";
import "./readable-content.css";

for (const [name, grammar] of Object.entries({
  bash,
  rust,
  javascript,
  typescript,
  json,
  python,
  go,
  yaml,
  sql,
  c,
  cpp,
  markup,
  css,
  toml,
}))
  SyntaxHighlighter.registerLanguage(name, grammar);

function CodeBlock({
  text,
  language,
  label,
}: {
  text: string;
  language?: string;
  label?: string;
}) {
  const [wrap, setWrap] = useState(false);
  const registered = readableLanguage(language);
  return (
    <section className={`readable-code-block${wrap ? " readable-wrap" : ""}`}>
      <div className="readable-code-heading">
        <span>{label || language || "Text"}</span>
        <Tooltip
          title={wrap ? "Keep original line spacing" : "Wrap long lines"}
        >
          <IconButton
            size="small"
            aria-label="Wrap long lines"
            aria-pressed={wrap}
            onClick={() => setWrap(!wrap)}
          >
            <WrapTextIcon sx={{ fontSize: 17 }} />
          </IconButton>
        </Tooltip>
      </div>
      {registered && text.length <= 32000 ? (
        <SyntaxHighlighter
          language={registered}
          useInlineStyles={false}
          wrapLongLines={wrap}
          className="readable-code"
          codeTagProps={{ className: `language-${registered}` }}
        >
          {text}
        </SyntaxHighlighter>
      ) : (
        <pre className="readable-code">
          <code>{text}</code>
        </pre>
      )}
    </section>
  );
}

function safeLink(url: string): string | undefined {
  return /^(?:https?:\/\/|mailto:|#[\w.-])/i.test(url) ? url : undefined;
}

function MarkdownContent({ text }: { text: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      urlTransform={(url) => safeLink(url)}
      components={{
        pre({ children }) {
          return <>{children}</>;
        },
        code({ className, children }) {
          const language = /language-([^\s]+)/.exec(className || "")?.[1];
          const value = String(children);
          return language || value.includes("\n") ? (
            <CodeBlock
              text={value}
              language={language}
              label={language || "Code"}
            />
          ) : (
            <code>{children}</code>
          );
        },
        a({ href, children }) {
          return href ? (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ) : (
            <span>{children}</span>
          );
        },
        img({ alt }) {
          return (
            <span className="readable-image-note">
              Image{alt ? `: ${alt}` : " reference"} (not loaded)
            </span>
          );
        },
        table({ children }) {
          return (
            <div className="readable-table">
              <table>{children}</table>
            </div>
          );
        },
      }}
    >
      {text}
    </ReactMarkdown>
  );
}

/** Presentation only: sources and downloads retain their original bytes. */
export function ReadableContent({
  text,
  language,
  kind = "markdown",
  complete = true,
}: {
  text: string;
  language?: string;
  kind?: ReadableKind;
  complete?: boolean;
}) {
  const large = text.length > 131072;
  const blocks = large
    ? [{ kind: "text" as const, text }]
    : readableBlocks(text, kind, complete, language);
  return (
    <div className="readable-content">
      {blocks.map((block, index) =>
        block.kind === "markdown" ? (
          <MarkdownContent key={index} text={block.text} />
        ) : (
          <CodeBlock
            key={index}
            text={block.text}
            language={block.language}
            label={
              block.kind === "code"
                ? block.language || "Code"
                : block.kind === "json"
                ? "JSON"
                : block.kind === "terminal"
                ? "Terminal output"
                : "Text"
            }
          />
        )
      )}
      {large && (
        <p className="readable-note">Large content shown as plain text.</p>
      )}
    </div>
  );
}
