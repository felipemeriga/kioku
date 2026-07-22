import {
  Box,
  Divider,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Stack,
  Tooltip,
  Typography,
  alpha,
} from "@mui/material";
import ChatBubbleOutlineIcon from "@mui/icons-material/ChatBubbleOutline";
import FolderOpenIcon from "@mui/icons-material/FolderOpen";
import SettingsIcon from "@mui/icons-material/Settings";
import LogoutIcon from "@mui/icons-material/Logout";

import { brand, fonts } from "../theme";

export type AppPage = "/" | "/documents" | "/settings";

interface IconRailProps {
  activePage: AppPage;
  onNavigate: (page: AppPage) => void;
  onTogglePanel: () => void;
  userEmail: string | undefined;
  onSignOut: () => void;
}

const NAV_ITEMS: {
  page: AppPage;
  icon: React.ReactNode;
  label: string;
  testId: string;
}[] = [
  {
    page: "/",
    icon: <ChatBubbleOutlineIcon fontSize="small" />,
    label: "Chat",
    testId: "nav-chat",
  },
  {
    page: "/documents",
    icon: <FolderOpenIcon fontSize="small" />,
    label: "Documents",
    testId: "nav-documents",
  },
  {
    page: "/settings",
    icon: <SettingsIcon fontSize="small" />,
    label: "Settings",
    testId: "nav-settings",
  },
];

export default function IconRail({
  activePage,
  onNavigate,
  onTogglePanel,
  userEmail,
  onSignOut,
}: IconRailProps) {
  const handleClick = (page: AppPage) => {
    if (page === activePage) {
      onTogglePanel();
    } else {
      onNavigate(page);
    }
  };

  return (
    <Box
      sx={{
        width: 200,
        height: "100vh",
        display: "flex",
        flexDirection: "column",
        bgcolor: brand.surface2,
        borderRight: `1px solid ${brand.line}`,
        flexShrink: 0,
      }}
    >
      {/* Brand block */}
      <Box
        sx={{
          display: "flex",
          alignItems: "center",
          gap: 1.25,
          px: 2,
          py: 2,
          borderBottom: `1px solid ${brand.line}`,
        }}
      >
        {/* Kanji brand mark — 記 in a magenta-glowing chrome frame.
            Reads as a stamped hanko / neon signage in cyberpunk Tokyo. */}
        <Box
          sx={{
            width: 34,
            height: 34,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            border: `1px solid ${brand.magenta}`,
            borderRadius: 1,
            background: `linear-gradient(135deg, ${brand.magenta}22 0%, ${brand.cyan}11 100%)`,
            boxShadow: `0 0 12px ${alpha(brand.magenta, 0.6)}, inset 0 0 8px ${alpha(brand.magenta, 0.25)}`,
            fontFamily: fonts.jp,
            fontWeight: 900,
            fontSize: "1.2rem",
            color: brand.magentaGlow,
            textShadow: `0 0 6px ${brand.magenta}, 0 0 12px ${brand.magenta}88`,
            flexShrink: 0,
          }}
        >
          記
        </Box>
        <Stack spacing={0}>
          <Typography
            variant="overline"
            sx={{
              fontFamily: fonts.jp,
              fontSize: "0.58rem",
              letterSpacing: "0.35em",
              color: brand.cyan,
              lineHeight: 1,
              textShadow: `0 0 6px ${brand.cyan}66`,
            }}
          >
            キオク
          </Typography>
          <Typography
            sx={{
              fontFamily: fonts.display,
              fontWeight: 700,
              fontSize: "1.05rem",
              letterSpacing: "0.08em",
              color: brand.text,
              lineHeight: 1.1,
              textTransform: "uppercase",
            }}
          >
            Kioku
          </Typography>
        </Stack>
      </Box>

      {/* Nav */}
      <List sx={{ px: 1, py: 1.25, flex: 1 }}>
        {NAV_ITEMS.map(({ page, icon, label, testId }) => {
          const isActive = page === activePage;
          return (
            <ListItemButton
              key={page}
              data-testid={testId}
              data-active={isActive}
              selected={isActive}
              onClick={() => handleClick(page)}
              sx={{
                py: 0.85,
                minHeight: 40,
              }}
            >
              <ListItemIcon
                sx={{
                  minWidth: 32,
                  color: isActive ? brand.violet2 : brand.muted,
                }}
              >
                {icon}
              </ListItemIcon>
              <ListItemText
                primary={label}
                primaryTypographyProps={{
                  fontFamily: fonts.display,
                  fontWeight: 600,
                  fontSize: "0.88rem",
                  color: isActive ? brand.text : brand.muted,
                }}
              />
            </ListItemButton>
          );
        })}
      </List>

      <Divider sx={{ borderColor: brand.line }} />

      {/* User block */}
      <Stack direction="row" spacing={1.25} alignItems="center" sx={{ px: 2, py: 1.5 }}>
        <Box
          sx={{
            width: 32,
            height: 32,
            borderRadius: "50%",
            display: "grid",
            placeItems: "center",
            background: `linear-gradient(135deg, ${brand.violet} 0%, ${brand.violet2} 100%)`,
            color: "#fff",
            fontFamily: fonts.display,
            fontWeight: 700,
            fontSize: "0.85rem",
            flexShrink: 0,
          }}
        >
          {userEmail?.charAt(0).toUpperCase() ?? "?"}
        </Box>
        <Stack sx={{ minWidth: 0, flex: 1 }} spacing={0}>
          <Typography
            noWrap
            title={userEmail ?? ""}
            sx={{
              fontFamily: fonts.body,
              fontSize: "0.78rem",
              color: brand.text,
              lineHeight: 1.25,
            }}
          >
            {userEmail ?? "—"}
          </Typography>
          <Typography
            variant="overline"
            sx={{
              fontFamily: fonts.mono,
              fontSize: "0.55rem",
              letterSpacing: "0.16em",
              color: brand.green,
              lineHeight: 1,
            }}
          >
            SIGNED IN
          </Typography>
        </Stack>
        <Tooltip title="Sign out">
          <IconButton
            onClick={onSignOut}
            data-testid="nav-signout"
            size="small"
            sx={{
              width: 30,
              height: 30,
              color: brand.muted,
              "&:hover": { color: brand.violet2, bgcolor: alpha(brand.violet, 0.1) },
            }}
          >
            <LogoutIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>
    </Box>
  );
}
