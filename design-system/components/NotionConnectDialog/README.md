Dialog to connect a Notion integration token, search a root page and bind it to a folder.

## Use
From NotionIntegrationSection or FolderIntegrationsDialog. Consumer supplies `open`, `rootFolders`, optional `fixedFolderId`, `onClose`, `onConnected`.

## Notes
- Source: `frontend/src/components/NotionIntegrationSection.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.NotionConnectDialog` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
