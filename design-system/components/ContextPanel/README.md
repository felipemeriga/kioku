The second column: conversations on the Chat page (with + new), the FolderTree on Documents.

## Use
Contextual navigation for the active page. Consumer supplies the conversation list and handlers; the folder view reads `?folder=` from the router.

## Notes
- Source: `frontend/src/components/ContextPanel.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.ContextPanel` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
