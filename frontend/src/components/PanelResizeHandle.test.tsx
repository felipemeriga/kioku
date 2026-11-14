import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { usePanelSize, readPanelSize } from "../hooks/usePanelSize";
import PanelResizeHandle from "./PanelResizeHandle";

function Panel({ direction = 1 }: { direction?: 1 | -1 }) {
  const size = usePanelSize("test", 264, 140, 440, 0);
  return (
    <PanelResizeHandle
      label="Resize test panel"
      controls="test-panel"
      {...size}
      onChange={size.setSize}
      direction={direction}
    />
  );
}
function memoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
    removeItem: (key: string) => {
      values.delete(key);
    },
    clear: () => values.clear(),
  };
}
beforeEach(() => {
  Object.defineProperty(window, "localStorage", {
    value: memoryStorage(),
    configurable: true,
  });
});
describe("workspace resize control", () => {
  it("bounds keyboard changes, persists across mounts and resets", () => {
    const view = render(<Panel />);
    let handle = screen.getByRole("separator", { name: "Resize test panel" });
    fireEvent.keyDown(handle, { key: "ArrowRight", shiftKey: true });
    expect(handle).toHaveAttribute("aria-valuenow", "296");
    fireEvent.keyDown(handle, { key: "Home" });
    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(handle).toHaveAttribute("aria-valuenow", "140");
    fireEvent.keyDown(handle, { key: "End" });
    expect(handle).toHaveAttribute("aria-valuenow", "440");
    view.unmount();
    render(<Panel />);
    handle = screen.getByRole("separator");
    expect(handle).toHaveAttribute("aria-valuenow", "440");
    fireEvent.doubleClick(handle);
    expect(handle).toHaveAttribute("aria-valuenow", "264");
  });
  it("reverses drawer keyboard direction", () => {
    render(<Panel direction={-1} />);
    const handle = screen.getByRole("separator");
    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(handle).toHaveAttribute("aria-valuenow", "276");
  });
  it("rolls back only Escape and keeps the resized width on capture interruption", () => {
    render(<Panel />);
    const handle = screen.getByRole("separator");
    handle.setPointerCapture = vi.fn();
    handle.hasPointerCapture = vi.fn(() => true);
    handle.releasePointerCapture = vi.fn();
    const pointer = (type: string, x: number) => {
      const event = new Event(type, { bubbles: true });
      Object.assign(event, {
        button: 0,
        isPrimary: true,
        pointerId: 7,
        clientX: x,
      });
      fireEvent(handle, event);
    };
    pointer("pointerdown", 100);
    pointer("pointermove", 160);
    expect(handle).toHaveFocus();
    expect(handle).toHaveAttribute("aria-valuenow", "324");
    fireEvent.keyDown(handle, { key: "Escape" });
    expect(handle).toHaveAttribute("aria-valuenow", "264");
    pointer("pointerdown", 100);
    pointer("pointermove", 200);
    pointer("pointercancel", 200);
    expect(handle).toHaveAttribute("aria-valuenow", "364");
    pointer("pointerdown", 200);
    pointer("pointermove", 100);
    pointer("lostpointercapture", 100);
    expect(handle).toHaveAttribute("aria-valuenow", "264");
    pointer("pointerdown", 100);
    pointer("pointermove", 200);
    pointer("pointerup", 200);
    expect(handle).toHaveAttribute("aria-valuenow", "364");
    expect(handle.releasePointerCapture).toHaveBeenCalledWith(7);
  });
  it("recovers from malformed or blocked storage without breaking layout", () => {
    for (const value of ["null", '"300"', "{}", "oops"]) {
      localStorage.setItem("kioku:panels:v1:test", value);
      expect(readPanelSize("test", 264, 140, 440)).toBe(264);
    }
    localStorage.setItem("kioku:panels:v1:test", "9000");
    expect(readPanelSize("test", 264, 140, 440)).toBe(440);
    Object.defineProperty(window, "localStorage", {
      get: () => {
        throw new Error("Blocked");
      },
      configurable: true,
    });
    render(<Panel />);
    fireEvent.keyDown(screen.getByRole("separator"), { key: "Home" });
    expect(screen.getByRole("separator")).toHaveAttribute(
      "aria-valuenow",
      "140",
    );
  });
});
