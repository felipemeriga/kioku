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
const markdown = `# Kioku agent journal — ${day}\n\n## 10:15 — Codex\n<!-- kioku-entry: {"id":"codex:s:t","agent":"codex"} -->\n\n- Found the cache invalidation issue.\n`;

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
                  { id: "codex:s:t", date: day, agent: "codex" },
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
                  entry_count: 1,
                  agents: ["codex"],
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
      screen.getByRole("button", { name: /1 journal entries/ }),
    ).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Markdown" }));
    expect(screen.getByText(/kioku-entry:.*codex:s:t/)).toBeInTheDocument();
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
