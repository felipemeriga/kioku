import { useRef } from "react";
import { Box, Tooltip } from "@mui/material";
import { brand } from "../theme";

export default function PanelResizeHandle({
  label,
  controls,
  size,
  min,
  max,
  initial,
  onChange,
  direction = 1,
  overlay = false,
}: {
  label: string;
  controls: string;
  size: number;
  min: number;
  max: number;
  initial: number;
  onChange: (size: number) => void;
  direction?: 1 | -1;
  overlay?: boolean;
}) {
  const drag = useRef<{ x: number; size: number; id: number } | null>(null);
  const change = (next: number) =>
    onChange(Math.round(Math.max(min, Math.min(max, next))));
  const cancel = () => {
    if (drag.current) {
      const previous = drag.current.size;
      drag.current = null;
      onChange(previous);
    }
  };
  return (
    <Tooltip
      title={`${label}. Drag or use arrow keys; double-click to reset.`}
      describeChild
      placement="top"
    >
      <Box
        role="separator"
        tabIndex={0}
        aria-label={label}
        aria-orientation="vertical"
        aria-controls={controls}
        aria-valuemin={min}
        aria-valuemax={max}
        aria-valuenow={size}
        aria-valuetext={`${size} pixels`}
        onDoubleClick={() => change(initial)}
        onPointerDown={(event) => {
          if (event.button !== 0 || event.isPrimary === false) return;
          event.preventDefault();
          event.currentTarget.focus();
          drag.current = { x: event.clientX, size, id: event.pointerId };
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          if (drag.current?.id === event.pointerId)
            change(
              drag.current.size + (event.clientX - drag.current.x) * direction,
            );
        }}
        onPointerUp={(event) => {
          if (drag.current?.id !== event.pointerId) return;
          drag.current = null;
          if (event.currentTarget.hasPointerCapture(event.pointerId))
            event.currentTarget.releasePointerCapture(event.pointerId);
        }}
        // Browsers can release capture when a window loses focus or native
        // gestures interrupt a drag. Keep the width the user already sees;
        // only an explicit Escape requests rollback to the starting width.
        onPointerCancel={() => {
          drag.current = null;
        }}
        onLostPointerCapture={() => {
          drag.current = null;
        }}
        onKeyDown={(event) => {
          const step = event.shiftKey ? 32 : 12;
          const next =
            event.key === "Home"
              ? min
              : event.key === "End"
                ? max
                : event.key === "ArrowLeft"
                  ? size - step * direction
                  : event.key === "ArrowRight"
                    ? size + step * direction
                    : null;
          if (event.key === "Escape" && drag.current) {
            event.preventDefault();
            event.stopPropagation();
            cancel();
          }
          if (next !== null) {
            event.preventDefault();
            change(next);
          }
        }}
        sx={{
          width: 12,
          flexShrink: 0,
          alignSelf: "stretch",
          minHeight: 48,
          cursor: "col-resize",
          touchAction: "none",
          userSelect: "none",
          position: overlay ? "absolute" : "relative",
          ...(overlay ? { left: 0, top: 0, bottom: 0, zIndex: 2 } : {}),
          "&::after": {
            content: '""',
            position: "absolute",
            top: "calc(50% - 22px)",
            height: 44,
            left: 5,
            width: 2,
            borderRadius: 2,
            bgcolor: brand.line,
          },
          "&:hover, &:focus-visible": {
            bgcolor: `${brand.cyan}12`,
            outline: `1px solid ${brand.cyan}`,
            outlineOffset: -1,
          },
          "&:hover::after, &:focus-visible::after": { bgcolor: brand.cyan },
        }}
      />
    </Tooltip>
  );
}
