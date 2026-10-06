Right drawer listing upload tasks with a six-dot stage track (parsing → storing), live chunk counts, done / error / duplicate states.

## Use
Shown while uploads process; auto-closes 10s after all finish. Consumer supplies `open`, `tasks`, `onClose`, `onInteract`.

## Notes
- Source: `frontend/src/components/IngestionDrawer.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.IngestionDrawer` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
