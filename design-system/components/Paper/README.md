> Offline preview snapshot. Verify current props, tokens, and behavior in
> `frontend/src/` before implementation. See [design-system guidance](../../README.md).

Themed MUI Paper — `surface` fill, `line` border and `shadow-paper`; the base of menus, dialogs and popovers.

## Use
Floating or raised surfaces. Prefer Card for in-flow content blocks.

## Notes
- Source: `frontend/src/theme.ts (MuiPaper)` (kioku@ba12918), bundled as-is; `window.Kioku.Paper` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
