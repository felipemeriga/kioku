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
const markdown = `# Kioku agent journal — ${day}\n\n## 10:15 — Codex\n<!-- kioku-entry: {"id":"codex:codex-session:t","agent":"codex","session_id":"codex-session"} -->\n\n- Found the cache invalidation issue.\n\n## 09:20 — Claude Code\n<!-- kioku-entry: {"id":"claude_code:claude-session:t","agent":"claude_code","session_id":"claude-session"} -->\n\n- Claude checked the same folder.\n`;

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
                  { id: "codex:codex-session:t", date: day, agent: "codex" },
                ],
                git_sha: null,
                updated_at: new Date().toISOString(),
              },
            ],
          }
        : url.includes("learning-days/")
          ? { status: "ok", markdown, revision: 2 }
          : {
              days: [
                {
                  journal_date: day,
                  revision: 2,
                  entry_count: 2,
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
      await screen.findByText("Found the cache invalidation issue."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /2 journal entries/ }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByLabelText("Session ID: codex-session"),
    ).toHaveTextContent("Session codex-s");
    expect(
      screen.getByLabelText("Session ID: claude-session"),
    ).toHaveTextContent("Session claude-s");
    const entries = document.querySelectorAll(".learnings-entry");
    expect(entries[0]).toHaveTextContent("Claude checked the same folder.");
    expect(entries[1]).toHaveTextContent("Found the cache invalidation issue.");
    fireEvent.click(screen.getByRole("button", { name: "Markdown" }));
    expect(
      screen.getByText(/kioku-entry:.*codex:codex-session:t/),
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
      await screen.findByText("Found the cache invalidation issue."),
    ).toBeInTheDocument();
  });
});
