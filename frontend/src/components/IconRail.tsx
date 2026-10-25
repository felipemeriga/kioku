import { useState } from "react";
import {
  Box,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Tooltip,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import ChatBubbleOutlineIcon from "@mui/icons-material/ChatBubbleOutline";
import FolderOpenIcon from "@mui/icons-material/FolderOpen";
import DevicesIcon from "@mui/icons-material/Devices";
import SettingsIcon from "@mui/icons-material/Settings";
import LogoutIcon from "@mui/icons-material/Logout";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import { brand, fonts } from "../theme";
export type AppPage = "/" | "/documents" | "/remotes" | "/settings";
interface IconRailProps {
  activePage: AppPage;
  onNavigate: (page: AppPage) => void;
  onTogglePanel: () => void;
  userEmail: string | undefined;
  onSignOut: () => void;
}
const items = [
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
    page: "/remotes",
    icon: <DevicesIcon fontSize="small" />,
    label: "Remotes",
    testId: "nav-remotes",
  },
  {
    page: "/settings",
    icon: <SettingsIcon fontSize="small" />,
    label: "Settings",
    testId: "nav-settings",
  },
] as const;
export default function IconRail({
  activePage,
  onNavigate,
  onTogglePanel,
  userEmail,
  onSignOut,
}: IconRailProps) {
  const compact = useMediaQuery(useTheme().breakpoints.down("lg"));
  const [userCollapsed, setCollapsed] = useState(
    () =>
      typeof localStorage !== "undefined" &&
      localStorage.getItem("kioku:rail-collapsed") === "1"
  );
  const collapsed = compact || userCollapsed;
  const toggle = () =>
    setCollapsed((previous) => {
      localStorage.setItem("kioku:rail-collapsed", previous ? "0" : "1");
      return !previous;
    });
  return (
    <Box
      component="nav"
      aria-label="Main navigation"
      sx={{
        width: collapsed ? { xs: 60, sm: 72 } : 200,
        height: "100dvh",
        display: "flex",
        flexDirection: "column",
        bgcolor: brand.surface2,
        borderRight: `1px solid ${brand.line}`,
        flexShrink: 0,
      }}
    >
      <Box
        sx={{
          height: 88,
          px: collapsed ? 0 : 2.5,
          display: "flex",
          alignItems: "center",
          justifyContent: collapsed ? "center" : "flex-start",
          gap: 1.25,
        }}
      >
        <Box
          aria-hidden="true"
          sx={{
            width: 32,
            height: 34,
            display: "grid",
            placeItems: "center",
            border: `1px solid ${brand.magenta}`,
            borderRadius: "4px",
            color: brand.magenta,
            fontFamily: fonts.jp,
            fontSize: 20,
          }}
        >
          記
        </Box>
        {!collapsed && (
          <Typography
            sx={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.03em" }}
          >
            Kioku
          </Typography>
        )}
      </Box>
      <List
        sx={{
          px: collapsed ? 0.5 : 1,
          py: 0,
          display: "flex",
          flexDirection: "column",
          gap: 0.5,
        }}
      >
        {items.map(({ page, icon, label, testId }) => (
          <Tooltip title={collapsed ? label : ""} placement="right" key={page}>
            <ListItemButton
              aria-label={label}
              aria-current={activePage === page ? "page" : undefined}
              data-testid={testId}
              data-active={activePage === page}
              selected={activePage === page}
              onClick={() =>
                page === activePage ? onTogglePanel() : onNavigate(page)
              }
              sx={{
                minHeight: 44,
                px: collapsed ? 0 : 1.5,
                justifyContent: collapsed ? "center" : "flex-start",
                color: activePage === page ? brand.text : brand.muted,
              }}
            >
              <ListItemIcon
                sx={{
                  minWidth: collapsed ? 0 : 32,
                  color: activePage === page ? brand.magenta : brand.muted,
                }}
              >
                {icon}
              </ListItemIcon>
              {!collapsed && (
                <ListItemText
                  primary={label}
                  primaryTypographyProps={{
                    fontSize: 15,
                    fontWeight: activePage === page ? 500 : 400,
                  }}
                />
              )}
            </ListItemButton>
          </Tooltip>
        ))}
      </List>
      <Box sx={{ flexGrow: 1 }} />
      {!compact && (
        <Tooltip title={collapsed ? "Expand rail" : "Collapse rail"}>
          <IconButton
            onClick={toggle}
            aria-label={collapsed ? "Expand rail" : "Collapse rail"}
            sx={{
              alignSelf: collapsed ? "center" : "flex-end",
              m: 1,
              color: brand.muted,
            }}
          >
            {collapsed ? (
              <ChevronRightIcon fontSize="small" />
            ) : (
              <ChevronLeftIcon fontSize="small" />
            )}
          </IconButton>
        </Tooltip>
      )}
      <Box
        sx={{
          borderTop: `1px solid ${brand.line}`,
          p: collapsed ? "16px 8px" : 2,
          display: "flex",
          alignItems: "center",
          flexDirection: collapsed ? "column" : "row",
          gap: 1.25,
        }}
      >
        <Box
          aria-hidden="true"
          sx={{
            width: 30,
            height: 30,
            flexShrink: 0,
            borderRadius: "50%",
            display: "grid",
            placeItems: "center",
            bgcolor: brand.raised,
            color: brand.magenta,
            fontWeight: 600,
          }}
        >
          {userEmail?.charAt(0).toUpperCase() ?? "?"}
        </Box>
        {!collapsed && (
          <Box sx={{ minWidth: 0, flex: 1 }}>
            <Typography title={userEmail} noWrap sx={{ fontSize: 12 }}>
              {userEmail}
            </Typography>
            <Typography sx={{ fontSize: 12, color: brand.muted }}>
              Signed in
            </Typography>
          </Box>
        )}
        <Tooltip title="Sign out">
          <IconButton
            aria-label="Sign out"
            onClick={onSignOut}
            data-testid="nav-signout"
            size="small"
            sx={{ color: brand.muted }}
          >
            <LogoutIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Box>
    </Box>
  );
}
