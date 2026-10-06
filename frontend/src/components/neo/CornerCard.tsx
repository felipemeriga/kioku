import { Box, type BoxProps } from "@mui/material";
import { brand, neonGlow } from "../../theme";

interface CornerCardProps extends BoxProps {
  color?: string;
  corners?: 2 | 4;
  glow?: boolean;
}

export default function CornerCard({
  color = brand.line,
  corners = 2,
  glow = false,
  sx,
  children,
  ...rest
}: CornerCardProps) {
  const size = 12;
  const c = (pos: Record<string, unknown>): Record<string, unknown> => ({
    content: '""',
    position: "absolute",
    width: size,
    height: size,
    pointerEvents: "none",
    ...pos,
  });
  const sxObj: Record<string, unknown> = {
    position: "relative",
    border: `1px solid ${color}`,
    backgroundColor: brand.surface,
    borderRadius: 1,
    ...(glow ? { boxShadow: neonGlow(color, 1) } : {}),
    "&::before": c({
      left: -1,
      top: -1,
      borderLeft: `2px solid ${color}`,
      borderTop: `2px solid ${color}`,
    }),
    "&::after": c({
      left: -1,
      bottom: -1,
      borderLeft: `2px solid ${color}`,
      borderBottom: `2px solid ${color}`,
    }),
    ...(corners === 4
      ? {
          "& > .nt-ctr": c({
            right: -1,
            top: -1,
            borderRight: `2px solid ${color}`,
            borderTop: `2px solid ${color}`,
          }),
          "& > .nt-cbr": c({
            right: -1,
            bottom: -1,
            borderRight: `2px solid ${color}`,
            borderBottom: `2px solid ${color}`,
          }),
        }
      : {}),
  };
  return (
    <Box
      {...rest}
      sx={{
        ...sxObj,
        ...(typeof sx === "object" && sx !== null && !Array.isArray(sx)
          ? sx
          : {}),
      }}
    >
      {corners === 4 && (
        <>
          <span className="nt-ctr" />
          <span className="nt-cbr" />
        </>
      )}
      {children}
    </Box>
  );
}
