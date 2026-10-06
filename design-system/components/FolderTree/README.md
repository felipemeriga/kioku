Lazy-loading folder tree with repo/folder icons, drag-and-drop targets (documents and OS files) and a per-folder menu (integrations, delete).

## Use
Document navigation. Consumer supplies `selectedFolderId`, `onSelectFolder`, `onRequestDelete`, `onRequestIntegrations`, and optional drop handlers.

## Notes
- Source: `frontend/src/components/FolderTree.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.FolderTree` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
