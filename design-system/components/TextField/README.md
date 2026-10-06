Themed outlined MUI TextField — `surface-2` fill, `line` border, `line-glow` on hover, magenta border + `shadow-focus` when focused.

## Use
All form inputs (folder names, API key names, Notion token, chat search). Use `helperText` + `error` for validation messages.

## Notes
- Source: `frontend/src/theme.ts (MuiTextField / MuiOutlinedInput)` (kioku@ba12918), bundled as-is; `window.Kioku.TextField` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
