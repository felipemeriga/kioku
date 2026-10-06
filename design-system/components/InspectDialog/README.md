Debug trace viewer with Reasoning, Tool calls and Chunks tabs (rerank scores, similarity, sources).

## Use
Opened from an assistant MessageBubble when debug mode was on. Consumer supplies `open`, `onClose`, `trace`.

## Notes
- Source: `frontend/src/components/InspectDialog.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.InspectDialog` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
