One chat message: user messages right-aligned in a magenta-tinted bubble; assistant messages left with the AutoAwesome mark, full GFM markdown (tables, code) and an Inspect button when a debug trace is attached.

## Use
Render each message. Consumer supplies `role`, `content` (markdown) and optional `debug` (opens InspectDialog). User line breaks are preserved and long tokens wrap.

## Notes
- Source: `frontend/src/components/MessageBubble.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.MessageBubble` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
