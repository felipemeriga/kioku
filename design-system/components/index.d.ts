// Kioku — window.Kioku. Types mirror frontend/src (felipemeriga/kioku@ba12918).
// Every component below is the app's real component, pre-wrapped in Kioku.Provider
// (ThemeProvider + CssBaseline + MemoryRouter + Auth + Toast + Conversations) and
// fed demo data by an offline /api mock. Pass `initialPath` to start the router elsewhere.
import type * as React from "react";
import type { ButtonProps as MuiButtonProps, IconButtonProps as MuiIconButtonProps, ChipProps as MuiChipProps, TextFieldProps as MuiTextFieldProps, PaperProps as MuiPaperProps, TooltipProps as MuiTooltipProps, AvatarProps as MuiAvatarProps, DividerProps as MuiDividerProps, SvgIconProps } from "@mui/material";

type Routed = { initialPath?: string };

// ── data shapes (src/lib/api.ts) ──
export interface Conversation { id: string; title: string; created_at: string; updated_at: string }
export interface DebugTrace {
  model?: string;
  reasoning: { round: number; text: string }[];
  tool_calls: { round: number; name: string; input: unknown; result_preview: string; is_error?: boolean }[];
  retrieval: { query?: string; source: string; source_type: string; symbol?: string | null; rerank_score?: number | null; similarity?: number | null; date?: string | null; content: string }[];
}
export interface Message { id: string; role: "user" | "assistant"; content: string; created_at: string; debug?: DebugTrace }
export type ChatStage = "thinking" | "searching" | "analyzing" | "generating";
export interface StageEvent { stage: ChatStage; docs?: number }
export type ChatModel = "haiku" | "sonnet";
export type ChatMode = "plain" | "agentic" | "deep";
export interface ChatFilters { topic?: string; keyword?: string; scopeFolderId?: string | null; scopeFilename?: string | null }
export interface ChatScope { folderId: string | null; folderName: string; filename?: string | null }
export interface DocumentInfo { source_filename: string; source_type: string; has_file: boolean; chunks: number; status: "processing" | "completed" | "failed"; created_at: string; folder_id: string | null }
export type IngestionStage = "uploading" | "parsing" | "chunking" | "extracting_metadata" | "embedding" | "storing" | "completed" | "error" | "duplicate";
export interface IngestionTask { id: string; user_id: string; filename: string; folder_id: string | null; stage: IngestionStage; stage_detail: string | null; error_message: string | null; chunks_total: number | null; chunks_done: number; duplicate: boolean; document_ids: string[]; created_at: string; updated_at: string }
export type AppPage = "/" | "/documents" | "/settings";
type OnSend = (message: string, filters?: ChatFilters, model?: ChatModel, mode?: ChatMode, debug?: boolean) => void;

// ── primitives (MUI 7 + theme.ts overrides) ──
export type ButtonProps = MuiButtonProps;
export type IconButtonProps = MuiIconButtonProps;
export type ChipProps = MuiChipProps;
export type TextFieldProps = MuiTextFieldProps;
export interface CardProps { title?: string; children?: React.ReactNode }
export type PaperProps = MuiPaperProps;
export type TooltipProps = MuiTooltipProps;
export type AvatarProps = MuiAvatarProps;
export type DividerProps = MuiDividerProps;
export interface NavItemProps { label: string; icon?: React.ReactNode; selected?: boolean; onClick?: () => void }
export interface TabsProps { tabs: string[]; value?: number }

// ── app components ──
export interface AppLayoutProps extends Routed { children: React.ReactNode }
export interface IconRailProps extends Routed { activePage: AppPage; onNavigate: (page: AppPage) => void; onTogglePanel: () => void; userEmail: string | undefined; onSignOut: () => void }
export interface ContextPanelProps extends Routed { activePage: AppPage; open: boolean; conversations: Conversation[]; selectedConversationId: string | null; onSelectConversation: (id: string) => void; onNewConversation: () => void; onDeleteConversation: (id: string) => void; onRequestDeleteFolder?: (folderId: string, folderName: string) => void; onNewFolder?: () => void }
export interface FolderTreeProps extends Routed { selectedFolderId: string | null; onSelectFolder: (id: string | null) => void; onRequestDelete: (folderId: string, folderName: string) => void; onRequestIntegrations: (folderId: string, folderName: string, kind?: "folder" | "repo") => void; onFileDropped?: (folderId: string | null, filename: string) => void; onOsFilesDropped?: (folderId: string | null, files: File[]) => void }
export interface ChatAreaProps extends Routed { messages: Message[]; streamingContent: string; isStreaming: boolean; currentStage: StageEvent | null; onSend: OnSend; scope?: ChatScope | null; onPickScope?: () => void; onClearScope?: () => void }
export interface ChatInputProps extends Routed { onSend: OnSend; disabled: boolean; scope?: ChatScope | null; onPickScope?: () => void; onClearScope?: () => void }
export interface MessageBubbleProps extends Routed { role: "user" | "assistant"; content: string; debug?: DebugTrace }
export interface ThinkingBarProps extends Routed { stage: StageEvent | null }
export interface InspectDialogProps extends Routed { open: boolean; onClose: () => void; trace: DebugTrace }
export interface ScopePickerDialogProps extends Routed { open: boolean; onClose: () => void; onSelect: (scope: ChatScope) => void }
export interface DocumentCardProps extends Routed { doc: DocumentInfo; selected?: boolean; onSelect?: (filename: string) => void; onDelete: (filename: string) => void; onDownload: (filename: string) => void; onMove?: (filename: string, folderId: string | null) => void; onOpen?: (filename: string) => void; onChat?: (filename: string) => void; variant?: "grid" | "list" }
export interface DocumentViewerDrawerProps extends Routed { filename: string | null; folderId?: string | null; onClose: () => void }
export interface MoveDialogProps extends Routed { open: boolean; title: string; onClose: () => void; onSelect: (folderId: string | null) => void }
export interface IngestionDrawerProps extends Routed { open: boolean; tasks: IngestionTask[]; onClose: () => void; onInteract: () => void }
export interface BriefingPanelProps extends Routed { folderId: string }
export interface DocumentationPanelProps extends Routed { folderId: string }
export interface FolderIntegrationsDialogProps extends Routed { open: boolean; folder: { id: string; name: string; kind?: "folder" | "repo" } | null; onClose: () => void }
export interface NotionIntegrationSectionProps extends Routed {}
export interface NotionConnectDialogProps extends Routed { open: boolean; rootFolders: { id: string; name: string }[]; fixedFolderId?: string; onClose: () => void; onConnected: () => void }
export interface NotionSyncBannerProps extends Routed { folderId: string; onPagesSynced?: () => void }
export interface Mem0IntegrationSectionProps extends Routed {}
export interface ErrorBoundaryProps extends Routed { children: React.ReactNode }
export interface ToastProps extends Routed {}
export type GitHubBrandIconProps = SvgIconProps;
export type NotionBrandIconProps = SvgIconProps;
export type Mem0BrandIconProps = SvgIconProps;

// ── screens: the App.tsx route tree at a path ──
export interface ScreenProps { path?: string }
export type ChatPageProps = ScreenProps;
export type DocumentsPageProps = ScreenProps;
export type FolderDetailPageProps = ScreenProps;
export type SettingsPageProps = ScreenProps;
export type LoginPageProps = ScreenProps;
export type CliAuthPageProps = ScreenProps;

export declare const Kioku: {
  Provider: React.FC<{ path?: string; children?: React.ReactNode }>;
  Screen: React.FC<ScreenProps>;
  theme: unknown; brand: Record<string, string>; fonts: { display: string; body: string; mono: string; jp: string };
  neonGlow(hex: string, intensity?: 1 | 2 | 3): string; scanlines: string;
  setSignedIn(v: boolean): void; mui: typeof import("@mui/material"); icons: Record<string, React.ComponentType<SvgIconProps>>; fixtures: Record<string, unknown>;
  Button: React.FC<ButtonProps>; IconButton: React.FC<IconButtonProps>; Chip: React.FC<ChipProps>; TextField: React.FC<TextFieldProps>; Card: React.FC<CardProps>; Paper: React.FC<PaperProps>; Tooltip: React.FC<TooltipProps>; Avatar: React.FC<AvatarProps>; Divider: React.FC<DividerProps>; NavItem: React.FC<NavItemProps>; Tabs: React.FC<TabsProps>;
  AppLayout: React.FC<AppLayoutProps>; IconRail: React.FC<IconRailProps>; ContextPanel: React.FC<ContextPanelProps>; FolderTree: React.FC<FolderTreeProps>;
  ChatArea: React.FC<ChatAreaProps>; ChatInput: React.FC<ChatInputProps>; MessageBubble: React.FC<MessageBubbleProps>; ThinkingBar: React.FC<ThinkingBarProps>; InspectDialog: React.FC<InspectDialogProps>; ScopePickerDialog: React.FC<ScopePickerDialogProps>;
  DocumentCard: React.FC<DocumentCardProps>; DocumentViewerDrawer: React.FC<DocumentViewerDrawerProps>; MoveDialog: React.FC<MoveDialogProps>; IngestionDrawer: React.FC<IngestionDrawerProps>;
  BriefingPanel: React.FC<BriefingPanelProps>; DocumentationPanel: React.FC<DocumentationPanelProps>; Mem0IntegrationSection: React.FC<Mem0IntegrationSectionProps>;
  FolderIntegrationsDialog: React.FC<FolderIntegrationsDialogProps>; NotionIntegrationSection: React.FC<NotionIntegrationSectionProps>; NotionConnectDialog: React.FC<NotionConnectDialogProps>; NotionSyncBanner: React.FC<NotionSyncBannerProps>;
  ErrorBoundary: React.FC<ErrorBoundaryProps>; Toast: React.FC<ToastProps>;
  GitHubBrandIcon: React.FC<SvgIconProps>; NotionBrandIcon: React.FC<SvgIconProps>; Mem0BrandIcon: React.FC<SvgIconProps>;
  ChatPage: React.FC<ScreenProps>; DocumentsPage: React.FC<ScreenProps>; FolderDetailPage: React.FC<ScreenProps>; SettingsPage: React.FC<ScreenProps>; LoginPage: React.FC<ScreenProps>; CliAuthPage: React.FC<ScreenProps>;
};
