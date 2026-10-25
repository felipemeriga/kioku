import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import NeoAtmosphere from "./NeoAtmosphere";

describe("retrowave atmosphere", () => {
  it("restores the original sun and grid as non-interactive decoration on login", () => {
    render(<NeoAtmosphere login />);
    const scene = screen.getByTestId("login-atmosphere");
    expect(scene).toHaveAttribute("aria-hidden", "true");
    expect(getComputedStyle(scene).pointerEvents).toBe("none");
    expect(screen.getByTestId("retro-sun")).toBeInTheDocument();
    expect(screen.getByTestId("retro-grid")).toBeInTheDocument();
    expect(scene.textContent).toBe("記憶");
  });
  it("keeps the workspace scene faded below the reading surfaces", () => {
    render(<NeoAtmosphere />);
    const scene = screen.getByTestId("app-atmosphere");
    expect(getComputedStyle(scene).opacity).toBe("0.16");
    expect(getComputedStyle(scene).zIndex).toBe("-1");
    expect(scene.textContent).toBe("");
  });
});
