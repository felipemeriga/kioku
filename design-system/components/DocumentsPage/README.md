Screen: the Documents route — folder tree, search/filter toolbar, grid/list toggle, upload, and document cards.

## Use
Reference for the documents composition. `path` can add `?folder=<id>`.

## Notes
- Source: `frontend/src/pages/DocumentsPage.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.DocumentsPage` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
