import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { renderWithProviders } from "../test/renderWithProviders";
import * as api from "../lib/api";
import LearningsPanel from "./LearningsPanel";

vi.mock("../lib/supabase", () => ({
  supabase: { auth: { getSession: vi.fn() } },
}));

const today = new Date();
const day = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
const codexSession = "019a7150-5887-7000-8000-123456789abc";
const claudeSession = "b9423292-d451-4d8c-a145-681df11a46d9";
const codexTime = new Date(`${day}T10:15:00`).getTime();
const claudeTime = new Date(`${day}T09:20:00`).getTime();
const syntheticTime = new Date(`${day}T11:00:00`).getTime();
const markdown = `# Kioku agent journal — ${day}\n\n## Codex session \`${codexSession}\`\n<!-- kioku-session: {"agent":"codex","session_id":"${codexSession}"} -->\n\n**About:** Fix cache invalidation\n\n**Done so far:** Found the cache issue.\n\n### ${codexTime} — Codex\n<!-- kioku-entry: {"id":"codex:${codexSession}:t","agent":"codex","session_id":"${codexSession}","captured_at":${codexTime}} -->\n\n- Found the cache invalidation issue.\n\n## Claude Code session \`${claudeSession}\`\n<!-- kioku-session: {"agent":"claude_code","session_id":"${claudeSession}"} -->\n\n**About:** Review folder\n\n**Done so far:** Checked the same folder.\n\n### ${claudeTime} — Claude Code\n<!-- kioku-entry: {"id":"claude_code:${claudeSession}:t","agent":"claude_code","session_id":"${claudeSession}","captured_at":"${new Date(claudeTime).toISOString()}"} -->\n\n- Claude checked the same folder.\n\n## Claude Code session \`kioku-e2e\`\n<!-- kioku-session: {"agent":"claude_code","session_id":"kioku-e2e"} -->\n\n**About:** Synthetic E2E entry\n\n**Done so far:** No session summary captured yet.\n\n### ${syntheticTime} — Claude Code\n<!-- kioku-entry: {"id":"claude_code:kioku-e2e:t","agent":"claude_code","session_id":"kioku-e2e","captured_at":${syntheticTime}} -->\n\n- Synthetic E2E entry.\n`;

describe("LearningsPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "apiFetch").mockImplementation(async (path) => {
      const url = String(path);
      const body = url.endsWith("/learnings")
        ? {
            learnings: [
              {
                id: "l1",
                topic_key: "cache-invalidation",
                statement: "Cache invalidation needs a folder revision.",
                status: "reported",
                source_entries: [
                  { id: `codex:${codexSession}:t`, date: day, agent: "codex" },
                ],
                git_sha: null,
                updated_at: new Date().toISOString(),
              },
            ],
          }
        : url.includes("learning-days/")
          ? {
              status: "ok",
              markdown,
              revision: 2,
              sessions: [
                {
                  agent: "codex",
                  session_id: codexSession,
                  title: "Fix cache invalidation",
                  summary: "Found the cache invalidation issue.",
                  computer_name: "Felipe MacBook",
                  entry_count: 1,
                  first_time: codexTime,
                  last_time: codexTime,
                },
                {
                  agent: "claude_code",
                  session_id: claudeSession,
                  title: "Review folder",
                  summary: "Checked the same folder.",
                  computer_name: "",
                  entry_count: 1,
                  first_time: claudeTime,
                  last_time: claudeTime,
                },
                {
                  agent: "claude_code",
                  session_id: "kioku-e2e",
                  title: "Synthetic E2E entry",
                  summary: "",
                  computer_name: "",
                  entry_count: 1,
                  first_time: syntheticTime,
                  last_time: syntheticTime,
                },
              ],
            }
          : {
              days: [
                {
                  journal_date: day,
                  revision: 2,
                  entry_count: 3,
                  agents: ["codex", "claude_code"],
                },
              ],
            };
      return new Response(JSON.stringify(body), { status: 200 });
    });
  });

  it("marks recorded dates and renders the actual journal entry", async () => {
    renderWithProviders(<LearningsPanel folderId="repo-1" />);
    expect(
      await screen.findByRole("button", { name: /Fix cache invalidation/ }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: /Fix cache invalidation/ }),
    );
    expect(
      screen.getByRole("region", { name: "Session overview" }),
    ).toHaveTextContent("Found the cache invalidation issue.");
    expect(
      screen.getByRole("button", { name: /3 journal entries/ }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByLabelText(`Session ID: ${codexSession}`),
    ).toHaveTextContent("Session 019a7150");
    expect(
      screen.getByLabelText(`Session ID: ${codexSession}`),
    ).toHaveAttribute("title", `Resume with: codex resume ${codexSession}`);
    expect(screen.queryByLabelText("Session ID: kioku-e2e")).toBeNull();
    const entries = document.querySelectorAll(".learnings-entry");
    expect(entries).toHaveLength(1);
    expect(entries[0]).toHaveTextContent("Found the cache invalidation issue.");
    fireEvent.click(screen.getByRole("button", { name: "← All sessions" }));
    fireEvent.click(screen.getByRole("button", { name: /Review folder/ }));
    expect(
      screen.getByLabelText(`Session ID: ${claudeSession}`),
    ).toHaveTextContent("Session b9423292");
    expect(document.querySelectorAll(".learnings-entry")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "Markdown" }));
    expect(
      screen.getByText(
        /kioku-entry:.*codex:019a7150-5887-7000-8000-123456789abc:t/,
      ),
    ).toBeInTheDocument();
  });

  it("links a current learning back to its source day", async () => {
    renderWithProviders(<LearningsPanel folderId="repo-1" />);
    fireEvent.click(screen.getByRole("tab", { name: "Learnings" }));
    expect(
      await screen.findByText("Cache invalidation needs a folder revision."),
    ).toBeInTheDocument();
    expect(screen.getByText("Agent report")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: `${day} · Codex` }));
    expect(
      await screen.findByRole("button", { name: /Fix cache invalidation/ }),
    ).toBeInTheDocument();
  });
});
