/** Small MCP client for journal sync, using the same scoped key as agents. */

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { readMcpEntry } from "./claude.js";
import { toStreamableHttpUrl } from "./codex.js";

export interface RemoteJournal {
  status: "ok" | "absent" | "unchanged" | "conflict" | "error";
  revision: number;
  markdown?: string;
  error?: string;
}

async function callJournalTool(
  repoRoot: string,
  name: string,
  args: Record<string, unknown>,
): Promise<RemoteJournal> {
  const entry = readMcpEntry(repoRoot);
  if (!entry) throw new Error("Kioku MCP configuration is missing");
  const url = new URL(toStreamableHttpUrl(entry.entry.url));
  const client = new Client({ name: "kioku-journal-cli", version: "1.0.0" });
  const transport = new StreamableHTTPClientTransport(url, {
    requestInit: { headers: { Authorization: `Bearer ${entry.key}` } },
  });
  try {
    await client.connect(transport);
    const result = await client.callTool(
      { name, arguments: args },
      undefined,
      { timeout: 30_000 },
    );
    const content = result.content as Array<{ type: string; text?: string }>;
    const text = content.find((part) => part.type === "text")?.text;
    if (result.isError || !text) throw new Error(`MCP ${name} failed`);
    const parsed = JSON.parse(text) as RemoteJournal;
    if (parsed.status === "error") throw new Error(parsed.error ?? `MCP ${name} failed`);
    return parsed;
  } finally {
    await client.close();
  }
}

export function getRemoteJournal(repoRoot: string, folder: string, date: string): Promise<RemoteJournal> {
  return callJournalTool(repoRoot, "get_agent_journal", { folder, date });
}

export function syncRemoteJournal(
  repoRoot: string, folder: string, date: string,
  markdown: string, baseRevision: number, contentSha256: string,
): Promise<RemoteJournal> {
  return callJournalTool(repoRoot, "sync_agent_journal", {
    folder, date, markdown, base_revision: baseRevision, content_sha256: contentSha256,
  });
}
