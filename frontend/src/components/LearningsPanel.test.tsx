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
const markdown = `# Kioku agent journal — ${day}\n\n## 10:15 — Codex\n<!-- kioku-entry: {"id":"codex:${codexSession}:t","agent":"codex","session_id":"${codexSession}"} -->\n\n- Found the cache invalidation issue.\n\n## 09:20 — Claude Code\n<!-- kioku-entry: {"id":"claude_code:${claudeSession}:t","agent":"claude_code","session_id":"${claudeSession}"} -->\n\n- Claude checked the same folder.\n\n## 11:00 — Claude Code\n<!-- kioku-entry: {"id":"claude_code:kioku-e2e:t","agent":"claude_code","session_id":"kioku-e2e"} -->\n\n- Synthetic E2E entry.\n`;

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
                  first_time: "10:15",
                  last_time: "10:15",
                },
                {
                  agent: "claude_code",
                  session_id: claudeSession,
                  title: "Review folder",
                  summary: "Checked the same folder.",
                  computer_name: "",
                  entry_count: 1,
                  first_time: "09:20",
                  last_time: "09:20",
                },
                {
                  agent: "claude_code",
                  session_id: "kioku-e2e",
                  title: "Synthetic E2E entry",
                  summary: "",
                  computer_name: "",
                  entry_count: 1,
                  first_time: "11:00",
                  last_time: "11:00",
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
