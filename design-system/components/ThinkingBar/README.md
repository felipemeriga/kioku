Four-segment progress strip for the agent's stages — thinking, searching, analyzing, generating — with a docs-found count.

## Use
Show while a chat answer is in flight; render nothing when `stage` is null.

## Notes
- Source: `frontend/src/components/ThinkingBar.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.ThinkingBar` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
