import { useState } from "react";
import {
  Box,
  Menu,
  MenuItem,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Tooltip,
  Typography,
  useMediaQuery,
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
  const compact = useMediaQuery("(max-width:780px)");
  const handset = useMediaQuery("(max-width:480px)");
  const [accountAnchor, setAccountAnchor] = useState<HTMLElement | null>(null);
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
  if (handset)
    return (
      <Box
        component="nav"
        aria-label="Main navigation"
        sx={{
          height: 64,
          minHeight: 64,
          px: "14px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          bgcolor: brand.surface2,
          borderBottom: `1px solid ${brand.line}`,
        }}
      >
        <IconButton
          aria-label="Account menu"
          onClick={(event) => setAccountAnchor(event.currentTarget)}
          sx={{
            border: `1px solid ${brand.magenta}`,
            color: brand.magenta,
            fontFamily: fonts.jp,
            fontSize: 23,
            width: 32,
            height: 34,
          }}
        >
          記
        </IconButton>
        <Box sx={{ display: "flex", gap: "1px" }}>
          {items.map(({ page, icon, label, testId }) => (
            <IconButton
              key={page}
              aria-label={label}
              aria-current={activePage === page ? "page" : undefined}
              data-testid={testId}
              data-active={activePage === page}
              onClick={() =>
                page === activePage ? onTogglePanel() : onNavigate(page)
              }
              sx={{
                width: 42,
                height: 42,
                color: activePage === page ? brand.magenta : brand.muted,
                bgcolor: activePage === page ? `${brand.magenta}12` : undefined,
                borderBottom:
                  activePage === page
                    ? `2px solid ${brand.magenta}`
                    : "2px solid transparent",
              }}
            >
              {icon}
            </IconButton>
          ))}
        </Box>
        <Menu
          anchorEl={accountAnchor}
          open={!!accountAnchor}
          onClose={() => setAccountAnchor(null)}
        >
          <MenuItem disabled>{userEmail}</MenuItem>
          <MenuItem data-testid="nav-signout" onClick={onSignOut}>
            Sign out
          </MenuItem>
        </Menu>
      </Box>
    );
  return (
    <Box
      component="nav"
      aria-label="Main navigation"
      sx={{
        width: collapsed ? 72 : { xs: 190, lg: 224 },
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
          height: 106,
          px: collapsed ? 0 : 3.5,
          display: "flex",
          alignItems: "center",
          justifyContent: collapsed ? "center" : "flex-start",
          gap: "13px",
        }}
      >
        <Box
          aria-hidden="true"
          sx={{
            width: 42,
            height: 42,
            display: "grid",
            placeItems: "center",
            border: `1px solid ${brand.magenta}`,
            borderRadius: "4px",
            color: brand.magenta,
            fontFamily: fonts.jp,
            fontSize: 26,
          }}
        >
          記
        </Box>
        {!collapsed && (
          <Box>
            <Typography
              sx={{
                fontFamily: fonts.jp,
                fontSize: 10,
                color: brand.muted,
                lineHeight: 1.4,
                letterSpacing: ".15em",
              }}
            >
              キオク
            </Typography>
            <Typography
              sx={{
                fontSize: 22,
                fontWeight: 600,
                lineHeight: 1.2,
                letterSpacing: "-.03em",
              }}
            >
              kioku
            </Typography>
          </Box>
        )}
      </Box>
      <List
        sx={{
          px: collapsed ? 0.5 : 1,
          py: 0,
          display: "flex",
          flexDirection: "column",
          gap: "3px",
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
                px: collapsed ? 0 : "14px",
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
      {!collapsed && (
        <Box
          sx={{
            mx: "10px",
            px: "16px",
            pt: 2.5,
            pb: 1.5,
            borderTop: `1px solid ${brand.line}`,
          }}
        >
          <Typography
            sx={{ fontSize: 12, color: brand.muted, lineHeight: 1.6 }}
          >
            Built for remembering.
            <br />
            Designed for reading.
          </Typography>
        </Box>
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
