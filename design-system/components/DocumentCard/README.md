A document tile (grid) or row (list): file-type icon in its type color, name, status pill, chunk count and age, with a context menu (open, chat, download, move, delete).

## Use
The documents grid and lists. Consumer supplies `doc` plus `onDelete`, `onDownload`, and optional `onSelect`, `onOpen`, `onChat`, `onMove`, `selected`, `variant`.

## Notes
- Source: `frontend/src/components/DocumentCard.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.DocumentCard` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
