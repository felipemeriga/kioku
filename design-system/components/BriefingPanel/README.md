A repo folder's briefing: staleness notice, index-status cards (git, graph, semantic code), and eight section cards (overview → activity) each with its icon/accent, status (auto / pinned / hybrid) and an editor.

## Use
The Briefing tab of a repo folder. Consumer supplies `folderId`; data comes from the briefing API.

## Notes
- Source: `frontend/src/components/BriefingPanel.tsx` (kioku@ba12918), bundled as-is; `window.Kioku.BriefingPanel` comes pre-wrapped in `Kioku.Provider`.
- Previews run on offline demo data (`Kioku.fixtures`); in the app the same component talks to the real API.
