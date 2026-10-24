import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/renderWithProviders";
import IconRail from "./IconRail";

const defaultProps = {
  activePage: "/" as const,
  onNavigate: vi.fn(),
  onTogglePanel: vi.fn(),
  userEmail: "test@example.com",
  onSignOut: vi.fn(),
};

describe("IconRail", () => {
  it("renders all navigation icons", () => {
    renderWithProviders(<IconRail {...defaultProps} />);
    expect(screen.getByTestId("nav-chat")).toBeInTheDocument();
    expect(screen.getByTestId("nav-documents")).toBeInTheDocument();
    expect(screen.getByTestId("nav-remotes")).toBeInTheDocument();
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
      />
    );
    await user.click(screen.getByTestId("nav-documents"));
    expect(onTogglePanel).toHaveBeenCalled();
  });

  it("navigates to Remotes and highlights its active state", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    const { rerender } = renderWithProviders(
      <IconRail {...defaultProps} onNavigate={onNavigate} />
    );
    await user.click(screen.getByTestId("nav-remotes"));
    expect(onNavigate).toHaveBeenCalledWith("/remotes");
    rerender(<IconRail {...defaultProps} activePage="/remotes" />);
    expect(screen.getByTestId("nav-remotes")).toHaveAttribute(
      "data-active",
      "true"
    );
  });

  it("renders user avatar with first letter of email", () => {
    renderWithProviders(<IconRail {...defaultProps} />);
    expect(screen.getByText("T")).toBeInTheDocument();
  });
});
