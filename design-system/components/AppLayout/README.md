The authenticated shell: IconRail on the left, the collapsible ContextPanel, and the page in the remaining space.

## Use
Wrap every signed-in page. Consumer supplies `children` (the page); navigation, conversations and folder deletion come from the providers.

## Notes
- Source: `frontend/src/components/AppLayout.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.AppLayout` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
