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
          gap: "10px",
          px: 2,
          py: 2,
          borderBottom: `1px solid ${brand.line}`,
        }}
      >
        {/* 34px hanko box — magenta border + dual-layer glow, 記 kanji inside */}
        <Box
          sx={{
            width: 34,
            height: 34,
            flexShrink: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            border: `1.5px solid ${brand.magenta}`,
            borderRadius: "6px",
            boxShadow: `0 0 4px ${brand.magenta}88, 0 0 16px ${brand.magenta}44`,
            fontFamily: fonts.jp,
            fontWeight: 900,
            fontSize: "18px",
            color: brand.magentaGlow,
          }}
        >
          記
        </Box>
        <Stack spacing={0} sx={{ lineHeight: 1 }}>
          <Typography
            component="span"
            sx={{
              fontFamily: fonts.dot,
              fontSize: "10px",
              letterSpacing: "0.3em",
              color: brand.cyan,
              lineHeight: 1,
              display: "block",
            }}
          >
            キオク
          </Typography>
          <Typography
            component="span"
            sx={{
              fontFamily: fonts.display,
              fontWeight: 700,
              fontSize: "18px",
              letterSpacing: "0.06em",
              color: brand.text,
              lineHeight: 1.15,
              textShadow: `0 0 10px ${brand.magenta}66`,
            }}
          >
            KIOKU
          </Typography>
        </Stack>
      </Box>

      {/* Nav */}
      <List
        sx={{
          px: "12px",
          py: "12px",
          flex: 1,
          display: "flex",
          flexDirection: "column",
          gap: "4px",
        }}
      >
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
                height: 42,
                minHeight: 42,
                px: "12px",
                py: 0,
                borderRadius: "3px",
                mb: 0,
                ...(isActive
                  ? {
                      background: `${brand.magenta}22`,
                      boxShadow: `inset 2px 0 0 ${brand.magenta}`,
                      color: brand.text,
                      "&:hover": { background: `${brand.magenta}33` },
                    }
                  : {
                      color: brand.muted,
                      "&:hover": { background: `${brand.magenta}10` },
                    }),
              }}
            >
              <ListItemIcon
                sx={{
                  minWidth: 32,
                  color: isActive ? brand.magenta : brand.muted,
                }}
              >
                {icon}
              </ListItemIcon>
              <ListItemText
                primary={label}
                primaryTypographyProps={{
                  fontFamily: fonts.display,
                  fontWeight: isActive ? 600 : 400,
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
      <Stack
        direction="row"
        spacing={1.25}
        alignItems="center"
        sx={{ px: 2, py: 1.5 }}
      >
        <Box
          sx={{
            width: 30,
            height: 30,
            borderRadius: "50%",
            display: "grid",
            placeItems: "center",
            background: `linear-gradient(135deg, ${brand.magenta}, ${brand.purple})`,
            color: "#fff",
            fontFamily: fonts.display,
            fontWeight: 700,
            fontSize: "13px",
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
              fontSize: "12px",
              color: brand.text,
              lineHeight: 1.25,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {userEmail ?? "—"}
          </Typography>
          <Typography
            component="span"
            sx={{
              fontFamily: fonts.mono,
              fontSize: "9px",
              letterSpacing: "0.2em",
              color: brand.green,
              lineHeight: 1,
            }}
          >
            ● SIGNED IN
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
              "&:hover": { color: brand.text, bgcolor: `${brand.magenta}14` },
            }}
          >
            <LogoutIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>
    </Box>
  );
}
