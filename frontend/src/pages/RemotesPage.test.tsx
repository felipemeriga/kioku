import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/renderWithProviders";
import RemotesPage from "./RemotesPage";

describe("Remotes preview", () => {
  it("discloses sample data and distinguishes collection from agent activity", () => {
    renderWithProviders(<RemotesPage />);
    expect(screen.getByRole("note")).toHaveTextContent(
      "Sample machines and activity"
    );
    expect(
      screen.getByText("Codex memories haven’t synced yet")
    ).toBeInTheDocument();
    expect(screen.getByText("Recently active")).toBeInTheDocument();
    expect(screen.getByText("Running")).toBeInTheDocument();
    expect(screen.getByText(/Session activity unknown/)).toBeInTheDocument();
    expect(
      screen.getByText(
        /Imported counts are memories received, not accepted findings/
      )
    ).toBeInTheDocument();
  });
  it("switches machines without retaining another machine’s sessions or issue", async () => {
    const user = userEvent.setup();
    renderWithProviders(<RemotesPage />);
    await user.click(screen.getByRole("button", { name: /Felipe’s MacBook/ }));
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "Felipe’s MacBook"
    );
    expect(screen.getByText("~/personal_projects/hive")).toBeInTheDocument();
    expect(
      screen.queryByText("Codex memories haven’t synced yet")
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/aea55265/)).not.toBeInTheDocument();
    expect(screen.getAllByText("Unknown")).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: /home-workstation/ }));
    expect(
      screen.getByRole("heading", { name: "This machine is offline" })
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Agents & sessions" })
    ).not.toBeInTheDocument();
  });
  it("filters by machine or platform and recovers from an empty search", async () => {
    const user = userEvent.setup();
    renderWithProviders(<RemotesPage />);
    const search = screen.getByRole("textbox", { name: "Find a machine" });
    await user.type(search, "macOS");
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "Felipe’s MacBook"
    );
    expect(
      screen.queryByRole("button", { name: /meriga-dev/ })
    ).not.toBeInTheDocument();
    await user.clear(search);
    await user.type(search, "unmatched");
    expect(screen.getByText(/No machines match/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Manage machine" })
    ).not.toBeInTheDocument();
    await user.clear(search);
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(
      "meriga-dev"
    );
  });
  it("explains unavailable setup and management instead of claiming success", async () => {
    const user = userEvent.setup();
    renderWithProviders(<RemotesPage />);
    await user.click(screen.getByRole("button", { name: "Connect machine" }));
    expect(
      within(screen.getByRole("dialog")).getByText(
        /does not register your computer/
      )
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close" }));
    await user.click(
      await screen.findByRole("button", { name: "Manage machine" })
    );
    expect(
      within(screen.getByRole("dialog")).getByText(
        /cannot change any machine settings/
      )
    ).toBeInTheDocument();
  });
  it("opens a clearly illustrative collection diagnostic", async () => {
    const user = userEvent.setup();
    renderWithProviders(<RemotesPage />);
    await user.click(screen.getByRole("button", { name: "View issue" }));
    expect(screen.getByRole("dialog")).toHaveAccessibleName(
      "Codex memory collection"
    );
    expect(
      within(screen.getByRole("dialog")).getByText(/example collection issue/)
    ).toBeInTheDocument();
  });
});
