The themed MUI Button — contained runs the magenta→purple `gradient-cta` with a `shadow-cta` glow; outlined is a `line` border that turns magenta on hover; text is a bare label.

## Use
One contained button per view for the main action (Ask, Generate, Connect). Outlined for secondary actions (Upload, Integrations), text for Cancel. Destructive: `color="error"`. Labels stay sentence case (`textTransform: none`), Rubik 600. White on magenta is 3.5:1 — keep labels at 14px semibold or larger and never put body copy on the gradient.

## Notes
- Source: `frontend/src/theme.ts (MuiButton)` (kioku@ba12918), bundled as-is; `window.Kioku.Button` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
