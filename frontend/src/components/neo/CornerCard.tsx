import { Box, type BoxProps } from "@mui/material";
import { brand, neonGlow } from "../../theme";

interface CornerCardProps extends BoxProps {
  color?: string;
  corners?: 2 | 4;
  glow?: boolean;
}

export default function CornerCard({
  color = brand.line,
  corners: _corners,
  glow = false,
  sx,
  children,
  ...rest
}: CornerCardProps) {
  void _corners;
  const sxObj: Record<string, unknown> = {
    position: "relative",
    border: `1px solid ${brand.line}`,
    borderRadius: 2,
    backgroundColor: brand.surface,
    ...(glow ? { borderColor: color, boxShadow: neonGlow(color, 1) } : {}),
  };
  return (
    <Box
      {...rest}
      role={rest.role ?? (rest.onClick ? "button" : undefined)}
      tabIndex={rest.tabIndex ?? (rest.onClick ? 0 : undefined)}
      onKeyDown={
        rest.onKeyDown ??
        (rest.onClick
          ? (event) => {
              if (
                event.target === event.currentTarget &&
                (event.key === "Enter" || event.key === " ")
              ) {
                event.preventDefault();
                (event.currentTarget as HTMLElement).click();
              }
            }
          : undefined)
      }
      sx={{
        ...sxObj,
        ...(typeof sx === "object" && sx !== null && !Array.isArray(sx)
          ? sx
          : {}),
      }}
    >
      {children}
    </Box>
  );
}
