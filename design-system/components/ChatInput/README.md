Composer row: attach, scope picker, filters, mode (Deep / Agentic / Plain) and model (Sonnet / Haiku) toggles, debug bug toggle, input and send.

## Use
Bottom of ChatArea. Consumer supplies `onSend(message, filters, model, mode, debug)`, `disabled`, and the active `scope` with pick/clear handlers.

## Notes
- Source: `frontend/src/components/ChatInput.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.ChatInput` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
