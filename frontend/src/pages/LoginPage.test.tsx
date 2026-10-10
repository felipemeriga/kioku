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
      // Email confirmation required → success with no session yet.
      signUp: vi
        .fn()
        .mockResolvedValue({ data: { session: null }, error: null }),
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

  it("tells the user to check their email after signing up", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LoginPage />, { initialEntries: ["/login"] });
    await user.click(screen.getByText("Sign up")); // toggle to sign-up
    await user.type(screen.getByLabelText("Email"), "new@example.com");
    await user.type(screen.getByLabelText("Password"), "password123");
    await user.click(screen.getByRole("button", { name: "Sign up" }));
    expect(
      await screen.findByText(/confirmation link to new@example.com/i)
    ).toBeInTheDocument();
  });

  it("shows retrowave background (sun + grid aria-hidden elements)", () => {
    const { container } = renderWithProviders(<LoginPage />, {
      initialEntries: ["/login"],
    });
    // Background scene elements are all aria-hidden; at least two must be present
    const hiddenEls = container.querySelectorAll('[aria-hidden="true"]');
    expect(hiddenEls.length).toBeGreaterThan(1);
  });
});
