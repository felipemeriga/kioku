import { createElement, useMemo, useState, type ReactNode } from "react";
import { syntax } from "./syntax";
import { IconButton, Tooltip } from "@mui/material";
import WrapTextIcon from "@mui/icons-material/WrapText";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  readableBlocks,
  readableLanguage,
  type ReadableKind,
} from "./contentBlocks";
import "./readable-content.css";

type SyntaxNode = ReturnType<typeof syntax.highlight>["children"][number];
function syntaxNode(node: SyntaxNode, key: number): ReactNode {
  if (node.type === "text") return node.value;
  if (node.type !== "element" || node.tagName !== "span") return null;
  const classes = Array.isArray(node.properties.className)
    ? node.properties.className.map(String).join(" ")
    : undefined;
  return createElement(
    "span",
    { className: classes, key },
    node.children.map((child, index) => syntaxNode(child as SyntaxNode, index))
  );
}

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
  const highlighted = useMemo(() => {
    if (!registered || !syntax.registered(registered) || text.length > 32000)
      return text;
    try {
      return syntax.highlight(registered, text).children.map(syntaxNode);
    } catch {
      return text;
    }
  }, [registered, text]);
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
      <pre className="readable-code">
        <code className={registered ? `language-${registered}` : undefined}>
          {highlighted}
        </code>
      </pre>
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
  const blocks = useMemo(
    () =>
      large
        ? [{ kind: "text" as const, text }]
        : readableBlocks(text, kind, complete, language),
    [large, text, kind, complete, language]
  );
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
