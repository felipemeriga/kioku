Screen: the Chat route (`/`) inside AppLayout — conversation list, messages and composer; sending streams a demo answer through the four ThinkingBar stages.

## Use
Reference for the full chat composition. `path` can add `?scope_folder=…&scope_name=…`.

## Notes
- Source: `frontend/src/pages/ChatPage.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.ChatPage` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
