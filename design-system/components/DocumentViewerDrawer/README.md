Right-side drawer that renders a document as markdown, highlighted code, PDF, image, audio/video or virtualized plain text, with its metadata.

## Use
Open a document in place. Consumer supplies `filename` (null = closed), optional `folderId`, `onClose`. The design-system bundle ships a light Prism build (python, ts/tsx, json, bash, markdown, sql, yaml).

## Notes
- Source: `frontend/src/components/DocumentViewerDrawer.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.DocumentViewerDrawer` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
