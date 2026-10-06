Thin progress banner for a running Notion sync on a folder — pages done / total and a magenta progress bar.

## Use
Top of a Notion-backed folder's documents. Consumer supplies `folderId`, optional `onPagesSynced`.

## Notes
- Source: `frontend/src/components/NotionSyncBanner.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.NotionSyncBanner` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
