Folder/document browser for narrowing a conversation's retrieval scope.

## Use
Opened from ChatInput's scope button. Consumer supplies `open`, `onClose`, `onSelect(scope)`.

## Notes
- Source: `frontend/src/components/ScopePickerDialog.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.ScopePickerDialog` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
