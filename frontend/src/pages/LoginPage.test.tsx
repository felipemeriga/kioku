// frontend/src/pages/LoginPage.test.tsx
import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test/renderWithProviders";
import LoginPage from "./LoginPage";

// Mock supabase
vi.mock("../lib/supabase", () => ({
  supabase: {
    auth: {
      signInWithPassword: vi.fn().mockResolvedValue({ error: null }),
      signUp: vi.fn().mockResolvedValue({ error: null }),
    },
  },
}));

describe("LoginPage", () => {
  it("renders sign in form by default", () => {
    renderWithProviders(<LoginPage />, { initialEntries: ["/login"] });
    expect(screen.getByText("Kioku")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("toggles to sign up form", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LoginPage />, { initialEntries: ["/login"] });
    await user.click(screen.getByText("Sign up"));
    expect(screen.getByRole("button", { name: "Sign up" })).toBeInTheDocument();
  });

  it("shows animated background", () => {
    const { container } = renderWithProviders(<LoginPage />, {
      initialEntries: ["/login"],
    });
    expect(container.querySelector('[data-testid="ambient-bg"]')).toBeInTheDocument();
  });
});
