import { useState } from "react";
import {
  Box,
  Menu,
  MenuItem,
  IconButton,
  Tooltip,
  useMediaQuery,
} from "@mui/material";
import ChatBubbleOutlineIcon from "@mui/icons-material/ChatBubbleOutline";
import FolderOpenIcon from "@mui/icons-material/FolderOpen";
import SettingsIcon from "@mui/icons-material/Settings";
import LogoutIcon from "@mui/icons-material/Logout";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import { brand, fonts } from "../theme";
export type AppPage = "/" | "/documents" | "/remotes" | "/settings";
interface IconRailProps {
  activePage: AppPage;
  onNavigate: (page: AppPage) => void;
  onTogglePanel: () => void;
  onCollapse: () => void;
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
  onCollapse,
  userEmail,
  onSignOut,
}: IconRailProps) {
  const handset = useMediaQuery("(max-width:480px)");
  const [accountAnchor, setAccountAnchor] = useState<HTMLElement | null>(null);
  return (
    <Box
      component="nav"
      aria-label="Main navigation"
      sx={{
        width: handset ? "100%" : 72,
        height: handset ? 64 : "100dvh",
        minHeight: handset ? 64 : undefined,
        display: "flex",
        flexDirection: handset ? "row" : "column",
        alignItems: "center",
        bgcolor: brand.surface2,
        borderRight: handset ? 0 : `1px solid ${brand.line}`,
        borderBottom: handset ? `1px solid ${brand.line}` : 0,
        flexShrink: 0,
        px: handset ? 1 : 0,
        py: handset ? 0 : 2,
        gap: handset ? 0.25 : 1,
      }}
    >
      <Tooltip
        title="Kioku home"
        describeChild
        placement={handset ? "bottom" : "right"}
      >
        <IconButton
          aria-label="Kioku home"
          onClick={() => onNavigate("/")}
          sx={{
            width: 40,
            height: 42,
            mb: handset ? 0 : 2,
            border: `1px solid ${brand.magenta}`,
            borderRadius: "4px",
            color: brand.magenta,
            fontFamily: fonts.jp,
            fontSize: 26,
          }}
        >
          記
        </IconButton>
      </Tooltip>
      {items.map(({ page, icon, label, testId }) => (
        <Tooltip
          title={label}
          describeChild
          placement={handset ? "bottom" : "right"}
          key={page}
        >
          <IconButton
            aria-label={label}
            aria-current={activePage === page ? "page" : undefined}
            data-testid={testId}
            data-active={activePage === page}
            onClick={() =>
              page === activePage ? onTogglePanel() : onNavigate(page)
            }
            sx={{
              width: 44,
              height: 44,
              borderRadius: "4px",
              color: activePage === page ? brand.magenta : brand.muted,
              bgcolor: activePage === page ? `${brand.magenta}12` : undefined,
              border:
                activePage === page
                  ? `1px solid ${brand.magenta}66`
                  : "1px solid transparent",
            }}
          >
            {icon}
          </IconButton>
        </Tooltip>
      ))}
      <Box sx={{ flex: 1 }} />
      <Tooltip
        title="Collapse navigation"
        describeChild
        placement={handset ? "bottom" : "right"}
      >
        <IconButton
          aria-label="Collapse navigation"
          onClick={onCollapse}
          sx={{ color: brand.muted }}
        >
          <ChevronLeftIcon fontSize="small" />
        </IconButton>
      </Tooltip>
      <Tooltip
        title={userEmail ? `Account: ${userEmail}` : "Account menu"}
        describeChild
        placement={handset ? "bottom" : "right"}
      >
        <IconButton
          aria-label="Account menu"
          aria-haspopup="menu"
          aria-expanded={!!accountAnchor}
          onClick={(event) => setAccountAnchor(event.currentTarget)}
          sx={{
            width: 30,
            height: 30,
            borderRadius: "50%",
            bgcolor: brand.raised,
            color: brand.magenta,
            fontSize: 13,
            fontWeight: 600,
          }}
        >
          {userEmail?.charAt(0).toUpperCase() ?? "?"}
        </IconButton>
      </Tooltip>
      {!handset && (
        <Tooltip title="Sign out" describeChild placement="right">
          <IconButton
            aria-label="Sign out"
            data-testid="nav-signout"
            onClick={onSignOut}
            sx={{ color: brand.muted }}
          >
            <LogoutIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      )}
      <Menu
        anchorEl={accountAnchor}
        open={!!accountAnchor}
        onClose={() => setAccountAnchor(null)}
      >
        <MenuItem disabled>{userEmail}</MenuItem>
        <MenuItem
          onClick={() => {
            setAccountAnchor(null);
            onNavigate("/settings");
          }}
        >
          Settings
        </MenuItem>
        <MenuItem
          data-testid={handset ? "nav-signout" : undefined}
          onClick={onSignOut}
        >
          Sign out
        </MenuItem>
      </Menu>
    </Box>
  );
}
