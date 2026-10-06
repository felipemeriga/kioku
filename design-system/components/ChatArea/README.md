The conversation view: MessageBubbles, the streaming answer, the ThinkingBar while the agent works, and ChatInput pinned at the bottom.

## Use
The main chat surface. Consumer supplies `messages`, `streamingContent`, `isStreaming`, `currentStage`, `onSend`, and optional scope handlers.

## Notes
- Source: `frontend/src/components/ChatArea.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.ChatArea` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
