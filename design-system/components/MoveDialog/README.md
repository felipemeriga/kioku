Folder browser for moving a document, with back navigation and a Root option.

## Use
From DocumentCard's Move action. Consumer supplies `open`, `title`, `onClose`, `onSelect(folderId)`.

## Notes
- Source: `frontend/src/components/MoveDialog.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.MoveDialog` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
