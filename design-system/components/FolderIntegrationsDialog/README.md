Per-folder integrations: GitHub (repo binding via `kioku init`), Notion (connect / sync / reconcile) and Mem0 status.

## Use
From the folder menu or the folder page's Integrations button. Consumer supplies `open`, `folder`, `onClose`.

## Notes
- Source: `frontend/src/components/FolderIntegrationsDialog.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.FolderIntegrationsDialog` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
