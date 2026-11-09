import { describe, it, expect, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/renderWithProviders";
import IconRail from "./IconRail";

const defaultProps = {
  activePage: "/" as const,
  onNavigate: vi.fn(),
  onTogglePanel: vi.fn(),
  onCollapse: vi.fn(),
  userEmail: "test@example.com",
  onSignOut: vi.fn(),
};

describe("IconRail", () => {
  it("renders all navigation icons", () => {
    renderWithProviders(<IconRail {...defaultProps} />);
    expect(screen.getByTestId("nav-chat")).toBeInTheDocument();
    expect(screen.getByTestId("nav-documents")).toBeInTheDocument();
    expect(screen.queryByTestId("nav-remotes")).not.toBeInTheDocument();
    expect(screen.getByTestId("nav-settings")).toBeInTheDocument();
  });

  it("highlights active page", () => {
    renderWithProviders(<IconRail {...defaultProps} activePage="/documents" />);
    const docsButton = screen.getByTestId("nav-documents");
    expect(docsButton).toHaveAttribute("data-active", "true");
  });

  it("fires onNavigate when clicking a nav icon", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    renderWithProviders(<IconRail {...defaultProps} onNavigate={onNavigate} />);
    await user.click(screen.getByTestId("nav-documents"));
    expect(onNavigate).toHaveBeenCalledWith("/documents");
  });

  it("fires onTogglePanel when clicking the active page icon", async () => {
    const user = userEvent.setup();
    const onTogglePanel = vi.fn();
    renderWithProviders(
      <IconRail
        {...defaultProps}
        activePage="/documents"
        onTogglePanel={onTogglePanel}
      />,
    );
    await user.click(screen.getByTestId("nav-documents"));
    expect(onTogglePanel).toHaveBeenCalled();
  });

  it("shows menu tooltips on keyboard focus and dismisses them with Escape", async () => {
    const user = userEvent.setup();
    // jsdom does not consistently track :focus-visible across Tab/Escape.
    // Model keyboard focus here; the actual browser behavior is checked separately.
    const matches = HTMLElement.prototype.matches;
    const focusVisible = vi
      .spyOn(HTMLElement.prototype, "matches")
      .mockImplementation(function (this: HTMLElement, selector: string) {
        return selector === ":focus-visible"
          ? document.activeElement === this
          : matches.call(this, selector);
      });
    renderWithProviders(<IconRail {...defaultProps} />);
    await user.tab();
    expect(screen.getByRole("button", { name: "Kioku home" })).toHaveFocus();
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Kioku home");
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.queryByRole("tooltip")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: "Kioku home" })).toHaveFocus();
    await user.tab();
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Chat");
    focusVisible.mockRestore();
  });

  it("requests full navigation collapse", async () => {
    const onCollapse = vi.fn();
    renderWithProviders(<IconRail {...defaultProps} onCollapse={onCollapse} />);
    await userEvent.click(
      screen.getByRole("button", { name: "Collapse navigation" }),
    );
    expect(onCollapse).toHaveBeenCalledOnce();
  });

  it("renders user avatar with first letter of email", () => {
    renderWithProviders(<IconRail {...defaultProps} />);
    expect(screen.getByText("T")).toBeInTheDocument();
  });
});
