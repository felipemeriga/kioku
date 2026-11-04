> Offline preview snapshot. Verify current props, tokens, and behavior in
> `frontend/src/` before implementation. See [design-system guidance](../../README.md).

The app's toast system (ToastProvider + `useToast`): bottom snackbars for success, info, warning and error, with an optional action.

## Use
Every async action reports through `useToast().showSuccess / showError`. The card fires a success toast on mount.

## Notes
- Source: `frontend/src/components/ToastProvider.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.Toast` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
