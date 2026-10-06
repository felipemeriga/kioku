// Kioku design-system bundle: the app's real components, themed and wired to demo data.
import "./mocks/fetchMock";
// Demo-only: auth errors from signed-out screens are expected, not crashes.
window.addEventListener("unhandledrejection", (e) => { if ((e.reason as { name?: string })?.name === "ApiError") e.preventDefault(); });
import * as React from "react";
import { MemoryRouter, Routes, Route, Navigate } from "react-router-dom";
import {
  ThemeProvider, CssBaseline,
  Button as MuiButton, IconButton as MuiIconButton, Chip as MuiChip, TextField as MuiTextField,
  Card as MuiCard, CardContent, Paper as MuiPaper, ListItemButton, ListItemIcon, ListItemText,
  Tooltip as MuiTooltip, Tabs as MuiTabs, Tab as MuiTab, Divider as MuiDivider, Avatar as MuiAvatar,
  Stack, Box, Typography, List,
} from "@mui/material";
import * as Mui from "@mui/material";

import theme, { brand, fonts, neonGlow, scanlines } from "@app/theme";
import { AuthProvider } from "@app/components/AuthProvider";
import { ProtectedRoute } from "@app/components/ProtectedRoute";
import ConversationsProvider from "@app/components/ConversationsProvider";
import ToastProvider, { useToast } from "@app/components/ToastProvider";
import ErrorBoundaryC from "@app/components/ErrorBoundary";
import AppLayoutC from "@app/components/AppLayout";
import BriefingPanelC from "@app/components/BriefingPanel";
import ChatAreaC from "@app/components/ChatArea";
import ChatInputC from "@app/components/ChatInput";
import ContextPanelC from "@app/components/ContextPanel";
import DocumentCardC from "@app/components/DocumentCard";
import DocumentViewerDrawerC from "@app/components/DocumentViewerDrawer";
import DocumentationPanelC from "@app/components/DocumentationPanel";
import FolderIntegrationsDialogC from "@app/components/FolderIntegrationsDialog";
import FolderTreeC from "@app/components/FolderTree";
import IconRailC from "@app/components/IconRail";
import IngestionDrawerC from "@app/components/IngestionDrawer";
import InspectDialogC from "@app/components/InspectDialog";
import { Mem0IntegrationSection as Mem0IntegrationSectionC } from "@app/components/Mem0IntegrationSection";
import MessageBubbleC from "@app/components/MessageBubble";
import MoveDialogC from "@app/components/MoveDialog";
import { NotionIntegrationSection as NotionIntegrationSectionC, NotionConnectDialog as NotionConnectDialogC } from "@app/components/NotionIntegrationSection";
import { NotionSyncBanner as NotionSyncBannerC } from "@app/components/NotionSyncBanner";
import ScopePickerDialogC from "@app/components/ScopePickerDialog";
import ThinkingBarC from "@app/components/ThinkingBar";
import { GitHubBrandIcon, NotionBrandIcon, Mem0BrandIcon } from "@app/components/BrandIcons";
import ChatPageC from "@app/pages/ChatPage";
import DocumentsPageC from "@app/pages/DocumentsPage";
import FolderDetailPageC from "@app/pages/FolderDetailPage";
import SettingsPageC from "@app/pages/SettingsPage";
import LoginPageC from "@app/pages/LoginPage";
import CliAuthPageC from "@app/pages/CliAuthPage";
import { __setSignedIn } from "./mocks/supabase";
import * as fixtures from "./mocks/fixtures";
import AddIcon from "@mui/icons-material/Add";
import DeleteIcon from "@mui/icons-material/Delete";
import SearchIcon from "@mui/icons-material/Search";
import SendIcon from "@mui/icons-material/Send";
import SettingsIcon from "@mui/icons-material/Settings";
import FolderIcon from "@mui/icons-material/Folder";
import DescriptionIcon from "@mui/icons-material/Description";
import AutoAwesomeIcon from "@mui/icons-material/AutoAwesome";
import CloseIcon from "@mui/icons-material/Close";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import RefreshIcon from "@mui/icons-material/Refresh";
import CloudUploadIcon from "@mui/icons-material/CloudUpload";
import ChatBubbleOutlineIcon from "@mui/icons-material/ChatBubbleOutline";
import AccountTreeIcon from "@mui/icons-material/AccountTree";
import HomeIcon from "@mui/icons-material/Home";
import MemoryIcon from "@mui/icons-material/Memory";
import HubIcon from "@mui/icons-material/Hub";
import FilterListIcon from "@mui/icons-material/FilterList";

const h = React.createElement;

/** Theme + router + auth + toasts + conversations — what App.tsx provides. */
export function Provider({ path = "/", children }: { path?: string; children?: React.ReactNode }) {
  return h(ThemeProvider, { theme },
    h(CssBaseline),
    h(MemoryRouter, { initialEntries: [path] },
      h(AuthProvider, null,
        h(ToastProvider, null,
          h(ConversationsProvider, null, children)))));
}

function wrap<P extends object>(name: string, C: React.ComponentType<P>, path = "/") {
  const W = (props: P & { initialPath?: string }) => {
    const { initialPath, ...rest } = props as P & { initialPath?: string };
    return h(Provider, { path: initialPath || path }, h(C as React.ComponentType<object>, rest));
  };
  W.displayName = name;
  return W;
}

/** The app's route tree at a given path, exactly as App.tsx mounts it. */
function Screen({ path = "/" }: { path?: string }) {
  const shell = (el: React.ReactNode) => h(ProtectedRoute, null, h(AppLayoutC, null, el));
  return h(Provider, { path },
    h(Routes, null,
      h(Route, { path: "/login", element: h(LoginPageC) }),
      h(Route, { path: "/cli-auth", element: h(CliAuthPageC) }),
      h(Route, { path: "/", element: shell(h(ChatPageC)) }),
      h(Route, { path: "/documents", element: shell(h(DocumentsPageC)) }),
      h(Route, { path: "/settings", element: shell(h(SettingsPageC)) }),
      h(Route, { path: "/folder/:folderId", element: shell(h(FolderDetailPageC)) }),
      h(Route, { path: "*", element: h(Navigate, { to: "/", replace: true }) })));
}
const screen = (name: string, def: string) => {
  const S = ({ path }: { path?: string }) => h(Screen, { path: path || def });
  S.displayName = name;
  return S;
};

// ── Themed primitives (MUI 7 + theme.ts overrides) ─────────────────────────
const Button = wrap("Button", MuiButton);
const IconButton = wrap("IconButton", MuiIconButton);
const Chip = wrap("Chip", MuiChip);
const TextField = wrap("TextField", MuiTextField);
const Tooltip = wrap("Tooltip", MuiTooltip);
const Avatar = wrap("Avatar", MuiAvatar);
const Divider = wrap("Divider", MuiDivider);
function CardC({ title, children, ...rest }: { title?: string; children?: React.ReactNode }) {
  return h(MuiCard, rest, h(CardContent, null,
    title ? h(Typography, { variant: "h6", sx: { mb: 1 } }, title) : null, children));
}
const Card = wrap("Card", CardC);
const Paper = wrap("Paper", MuiPaper);
function NavItemC({ icon, label, selected, onClick }: { icon?: React.ReactNode; label: string; selected?: boolean; onClick?: () => void }) {
  return h(ListItemButton, { selected, onClick }, icon ? h(ListItemIcon, { sx: { minWidth: 36 } }, icon) : null, h(ListItemText, { primary: label }));
}
const NavItem = wrap("NavItem", NavItemC);
function TabsC({ tabs, value: v0 = 0 }: { tabs: string[]; value?: number }) {
  const [v, setV] = React.useState(v0);
  return h(MuiTabs, { value: v, onChange: (_e: unknown, n: number) => setV(n) }, tabs.map((t) => h(MuiTab, { key: t, label: t })));
}
const Tabs = wrap("Tabs", TabsC);

/** Fires a toast through the app's ToastProvider. */
function ToastDemoC() {
  const toast = useToast() as unknown as Record<string, (...a: unknown[]) => void>;
  React.useEffect(() => { const t = setTimeout(() => toast.showSuccess?.("Folder “RAG papers” created."), 300); return () => clearTimeout(t); }, []);
  return h(Stack, { direction: "row", spacing: 1 },
    h(MuiButton, { variant: "outlined", onClick: () => (toast.showSuccess || toast.success)?.("Folder created.") }, "Success toast"),
    h(MuiButton, { variant: "outlined", onClick: () => toast.showError?.(new Error("Upload failed for “notes.pdf”."), "Upload failed.") }, "Error toast"));
}

const KiokuNS = {
  // providers + helpers
  Provider, Screen, theme, brand, fonts, neonGlow, scanlines, fixtures, useToast,
  setSignedIn: __setSignedIn,
  icons: { Add: AddIcon, Delete: DeleteIcon, Search: SearchIcon, Send: SendIcon, Settings: SettingsIcon, Folder: FolderIcon, Description: DescriptionIcon, AutoAwesome: AutoAwesomeIcon, Close: CloseIcon, ContentCopy: ContentCopyIcon, Refresh: RefreshIcon, CloudUpload: CloudUploadIcon, ChatBubbleOutline: ChatBubbleOutlineIcon, AccountTree: AccountTreeIcon, Home: HomeIcon, Memory: MemoryIcon, Hub: HubIcon, FilterList: FilterListIcon },
  mui: Mui, Box, Stack, Typography, List,
  // primitives
  Button, IconButton, Chip, TextField, Card, Paper, Tooltip, Avatar, Divider, NavItem, Tabs,
  // app components
  AppLayout: wrap("AppLayout", AppLayoutC),
  IconRail: wrap("IconRail", IconRailC),
  ContextPanel: wrap("ContextPanel", ContextPanelC, "/documents"),
  FolderTree: wrap("FolderTree", FolderTreeC, "/documents"),
  ChatArea: wrap("ChatArea", ChatAreaC),
  ChatInput: wrap("ChatInput", ChatInputC),
  MessageBubble: wrap("MessageBubble", MessageBubbleC),
  ThinkingBar: wrap("ThinkingBar", ThinkingBarC),
  InspectDialog: wrap("InspectDialog", InspectDialogC),
  ScopePickerDialog: wrap("ScopePickerDialog", ScopePickerDialogC),
  DocumentCard: wrap("DocumentCard", DocumentCardC, "/documents"),
  DocumentViewerDrawer: wrap("DocumentViewerDrawer", DocumentViewerDrawerC),
  MoveDialog: wrap("MoveDialog", MoveDialogC),
  IngestionDrawer: wrap("IngestionDrawer", IngestionDrawerC),
  BriefingPanel: wrap("BriefingPanel", BriefingPanelC, "/folder/f-kioku"),
  DocumentationPanel: wrap("DocumentationPanel", DocumentationPanelC, "/folder/f-kioku"),
  FolderIntegrationsDialog: wrap("FolderIntegrationsDialog", FolderIntegrationsDialogC),
  NotionIntegrationSection: wrap("NotionIntegrationSection", NotionIntegrationSectionC, "/settings"),
  NotionConnectDialog: wrap("NotionConnectDialog", NotionConnectDialogC, "/settings"),
  NotionSyncBanner: wrap("NotionSyncBanner", NotionSyncBannerC),
  Mem0IntegrationSection: wrap("Mem0IntegrationSection", Mem0IntegrationSectionC, "/settings"),
  ErrorBoundary: wrap("ErrorBoundary", ErrorBoundaryC),
  Toast: wrap("Toast", ToastDemoC),
  GitHubBrandIcon: wrap("GitHubBrandIcon", GitHubBrandIcon),
  NotionBrandIcon: wrap("NotionBrandIcon", NotionBrandIcon),
  Mem0BrandIcon: wrap("Mem0BrandIcon", Mem0BrandIcon),
  // screens (full routes, AppLayout included)
  ChatPage: screen("ChatPage", "/"),
  DocumentsPage: screen("DocumentsPage", "/documents"),
  FolderDetailPage: screen("FolderDetailPage", "/folder/f-kioku"),
  SettingsPage: screen("SettingsPage", "/settings"),
  LoginPage: screen("LoginPage", "/login"),
  CliAuthPage: screen("CliAuthPage", "/cli-auth?req=demo-req"),
};

(window as unknown as Record<string, unknown>).Kioku = KiokuNS;
