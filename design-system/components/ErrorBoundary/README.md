App-level crash screen with the error message, Reload and Copy details.

## Use
Wraps the whole app. Consumer supplies `children`.

## Notes
- Source: `frontend/src/components/ErrorBoundary.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.ErrorBoundary` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
