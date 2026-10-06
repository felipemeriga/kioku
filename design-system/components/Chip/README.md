Themed MUI Chip — JetBrains Mono, 3px radius, 0.5px tracking; outlined chips use the `line` border.

## Use
Status pills (completed / processing / failed), filters, model and mode badges, scope tags with `onDelete`. Use `color` for meaning (secondary = AI, success, warning, error) and pair it with a word — never color alone.

## Notes
- Source: `frontend/src/theme.ts (MuiChip)` (kioku@ba12918), bundled as-is; `window.Kioku.Chip` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
