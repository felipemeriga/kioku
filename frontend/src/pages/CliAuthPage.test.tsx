import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { MemoryRouter } from "react-router-dom";
import { render } from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import { CssBaseline } from "@mui/material";
import theme from "../theme";
import { renderWithProviders } from "../test/renderWithProviders";
import CliAuthPage from "./CliAuthPage";

const mockUseAuth = vi.fn(
  (): { session: { user: { email: string } } | null; loading: boolean } => ({
    session: { user: { email: "me@example.com" } },
    loading: false,
  }),
);
vi.mock("../hooks/useAuth", () => ({
  useAuth: () => mockUseAuth(),
}));
const complete = vi.fn().mockResolvedValue(undefined);
const deny = vi.fn().mockResolvedValue(undefined);
const deviceInfo = vi.fn().mockResolvedValue({ hostname: "laptop", os: "darwin", valid: true, expired: false });
vi.mock("../lib/api", () => ({
  deviceInfo: (...a: unknown[]) => deviceInfo(...a),
  deviceComplete: (...a: unknown[]) => complete(...a),
  deviceDeny: (...a: unknown[]) => deny(...a),
}));

beforeEach(() => {
  complete.mockClear();
  deny.mockClear();
  deviceInfo.mockClear();
  mockUseAuth.mockReturnValue({ session: { user: { email: "me@example.com" } }, loading: false });
  deviceInfo.mockResolvedValue({ hostname: "laptop", os: "darwin", valid: true, expired: false });
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

  it("redirects unauthenticated users to /login with redirect param", async () => {
    mockUseAuth.mockReturnValue({ session: null, loading: false });
    render(
      <MemoryRouter initialEntries={["/cli-auth?req=abc123"]}>
        <ThemeProvider theme={theme}>
          <CssBaseline />
          <Routes>
            <Route path="/cli-auth" element={<CliAuthPage />} />
            <Route path="/login" element={<div>login-sentinel</div>} />
          </Routes>
        </ThemeProvider>
      </MemoryRouter>,
    );
    await screen.findByText("login-sentinel");
  });
});
