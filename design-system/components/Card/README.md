Themed MUI Card — `gradient-card` fill (surface → surface-2) with a 1px `line` border.

## Use
Grouping a self-contained block: integration sections, settings groups, briefing sections. `Kioku.Card` takes a `title` and children; compose `Kioku.mui.Card` + `CardContent` for anything richer.

## Notes
- Source: `frontend/src/theme.ts (MuiCard)` (kioku@ba12918), bundled as-is; `window.Kioku.Card` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
