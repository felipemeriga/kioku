/** Read-only terminal access to the same scoped MCP tools used by agents. */
import { dirname, resolve } from "node:path";
import { existsSync } from "node:fs";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { readMcpEntry } from "./claude.js";
import { toStreamableHttpUrl } from "./codex.js";

export function findRecallBinding(start = process.cwd()) {
  let dir = resolve(start);
  for (;;) {
    const entry = readMcpEntry(dir);
    if (entry) return entry;
    // An explicit configuration must never silently fall back to a parent's scope.
    if (existsSync(resolve(dir, ".mcp.json"))) {
      throw new Error(
        "No valid Kioku connection in .mcp.json. Run kioku init here."
      );
    }
    const parent = dirname(dir);
    if (parent === dir)
      throw new Error(
        "Run this command inside a repository connected with kioku init."
      );
    dir = parent;
  }
}

export function decodeRecallResult(result: {
  [key: string]: unknown;
  isError?: unknown;
  content?: unknown;
}): unknown {
  const parts = (Array.isArray(result.content) ? result.content : []) as Array<{
    type: string;
    text?: string;
  }>;
  const text = parts
    .filter((p) => p.type === "text")
    .map((p) => p.text ?? "")
    .join("\n");
  if (result.isError || !text)
    throw new Error("Kioku MCP tool failed. Check your connection and scope.");
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    if (text.startsWith("Error:")) throw new Error(text);
    return text;
  }
  if (
    data &&
    typeof data === "object" &&
    "status" in data &&
    data.status === "error"
  ) {
    const error = data as { code?: string; detail?: { code?: string } };
    throw new Error(
      `Kioku: ${error.code ?? error.detail?.code ?? "tool unavailable"}`
    );
  }
  return data;
}

export async function callRecallTool(
  name: string,
  args: Record<string, unknown>
): Promise<unknown> {
  const binding = findRecallBinding();
  const client = new Client({ name: "kioku-recall-cli", version: "1.0.0" });
  const transport = new StreamableHTTPClientTransport(
    new URL(toStreamableHttpUrl(binding.entry.url)),
    {
      requestInit: { headers: { Authorization: `Bearer ${binding.key}` } },
    }
  );
  try {
    await client.connect(transport, { timeout: 30_000 });
    return decodeRecallResult(
      await client.callTool({ name, arguments: args }, undefined, {
        timeout: 120_000,
      })
    );
  } finally {
    await client.close();
  }
}
