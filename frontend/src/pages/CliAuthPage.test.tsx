import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/renderWithProviders";
import CliAuthPage from "./CliAuthPage";

vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({ session: { user: { email: "me@example.com" } }, loading: false }),
}));
const complete = vi.fn().mockResolvedValue(undefined);
const deny = vi.fn().mockResolvedValue(undefined);
vi.mock("../lib/api", () => ({
  deviceInfo: vi.fn().mockResolvedValue({ hostname: "laptop", os: "darwin", valid: true, expired: false }),
  deviceComplete: (...a: unknown[]) => complete(...a),
  deviceDeny: (...a: unknown[]) => deny(...a),
}));

beforeEach(() => {
  complete.mockClear();
  deny.mockClear();
});

describe("CliAuthPage", () => {
  it("shows device info and authorizes", async () => {
    renderWithProviders(<CliAuthPage />, { initialEntries: ["/cli-auth?req=abc123"] });
    await screen.findByText(/laptop/);
    await userEvent.click(screen.getByRole("button", { name: /authorize/i }));
    await waitFor(() => expect(complete).toHaveBeenCalledWith("abc123"));
    await screen.findByText(/signed in/i);
  });

  it("shows an error when req is missing", async () => {
    renderWithProviders(<CliAuthPage />, { initialEntries: ["/cli-auth"] });
    await screen.findByText(/invalid login link/i);
  });
});
