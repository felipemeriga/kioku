import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { useState } from "react";
import { renderWithProviders } from "../test/renderWithProviders";
import * as api from "../lib/api";
import {
  HistorySearchToolbar,
  HistorySearchResults,
  SearchExcerpt,
} from "./HistorySearch";
import { emptyHistoryFilters, type HistoryFilters } from "../lib/historySearch";
vi.mock("../lib/supabase", () => ({
  supabase: { auth: { getSession: vi.fn() } },
}));
beforeEach(() => vi.restoreAllMocks());
function Toolbar() {
  const [filters, setFilters] = useState<HistoryFilters>({
    ...emptyHistoryFilters,
  });
  return <HistorySearchToolbar filters={filters} onChange={setFilters} />;
}
describe("history search", () => {
  it("defaults to all dates and clears submitted queries", () => {
    renderWithProviders(<Toolbar />);
    expect(screen.getByText("All dates")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "Search history" }), {
      target: { value: "decoder" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByRole("textbox", { name: "Search history" })).toHaveValue(
      ""
    );
  });
  it("escapes snippets and highlights literal matches", () => {
    const { container } = renderWithProviders(
      <SearchExcerpt
        text={"<script>memory</script>"}
        filters={{ ...emptyHistoryFilters, q: "memory" }}
      />
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("mark")).toHaveTextContent("memory");
  });
  it("passes all-date filters and cancellation, separates title hits, opens exact dates", async () => {
    const mock = vi.spyOn(api, "apiFetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          total_sessions: 1,
          total_entries: 1,
          has_more: false,
          sessions: [
            {
              agent: "codex",
              session_id: "session",
              title: "Decoder investigation",
              dates: ["2026-10-29", "2026-11-05"],
              title_match: true,
              overview_match: false,
              matches: [
                {
                  id: "entry",
                  date: "2026-10-29",
                  excerpt: "Fixed decoder lifecycle",
                },
              ],
            },
          ],
        })
      )
    );
    const open = vi.fn();
    renderWithProviders(
      <HistorySearchResults
        folderId="repo/id"
        timezone="UTC"
        filters={{ ...emptyHistoryFilters, q: "decoder" }}
        onOpen={open}
      />
    );
    await screen.findByText("Title match");
    expect(mock).toHaveBeenCalledWith(
      expect.stringContaining("repo%2Fid/history-search?q=decoder"),
      { signal: expect.any(AbortSignal) }
    );
    expect(String(mock.mock.calls[0][0])).not.toContain("date_from");
    fireEvent.click(
      screen.getByRole("button", {
        name: /2026-10-29.*Fixed decoder lifecycle/,
      })
    );
    expect(open).toHaveBeenCalledWith(
      expect.objectContaining({ session_id: "session" }),
      "2026-10-29",
      "entry"
    );
  });
  it("rejects reversed dates before requesting the server", () => {
    const mock = vi.spyOn(api, "apiFetch");
    renderWithProviders(
      <HistorySearchResults
        folderId="repo"
        timezone="UTC"
        filters={{
          ...emptyHistoryFilters,
          date_from: "2026-11-05",
          date_to: "2026-10-01",
        }}
        onOpen={vi.fn()}
      />
    );
    expect(screen.getByRole("alert")).toHaveTextContent("end date");
    expect(mock).not.toHaveBeenCalled();
  });
});
