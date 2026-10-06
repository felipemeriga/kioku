Themed MUI IconButton — 3px radius and a 8% magenta hover wash.

## Use
Toolbar and row actions (copy, refresh, delete, close). Always give it an `aria-label`; wrap in a Tooltip when the icon isn't self-evident.

## Notes
- Source: `frontend/src/theme.ts (MuiIconButton)` (kioku@ba12918), bundled as-is; `window.Kioku.IconButton` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
