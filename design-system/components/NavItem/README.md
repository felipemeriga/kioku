A themed MUI ListItemButton as the app uses it in side lists — 3px radius, `2px 8px` margin, selected = 13% magenta fill with a 2px magenta left edge and magenta icon.

## Use
Conversation lists, folder lists, any selectable side-panel row. `Kioku.NavItem` takes `label`, `icon`, `selected`, `onClick`.

## Notes
- Source: `frontend/src/theme.ts (MuiListItemButton)` (kioku@ba12918), bundled as-is; `window.Kioku.NavItem` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
