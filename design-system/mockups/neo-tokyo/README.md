# Neo-Tokyo restyle — mockups

Design-canvas boards for the cyberpunk 80s Japan restyle of Kioku's **existing** screens (no new features). Each `.dc.html` is one artboard; `canvas.json` is the layout. They render in the Kioku design canvas (Claude Design), which supplies the `support.js` runtime — opened directly in a browser they show unstyled markup only.

| Board | Screen |
|---|---|
| `Main.dc.html` | 01 · Chat |
| `Dossier.dc.html` | 02 · Folder detail — Briefing |
| `Boot.dc.html` | 03 · Login |
| `Archive.dc.html` | 04 · Documents |
| `Cache.dc.html` | 05 · Folder detail — Memory |
| `Config.dc.html` | 06 · Settings |
| `Viewer.dc.html` | 07 · Document viewer drawer |
| `Debugger.dc.html` | 08 · Inspect dialog |
| `Ingest.dc.html` | 09 · Ingestion drawer |
| `Integrations.dc.html` | 10 · Folder integrations dialog |
| `Handshake.dc.html` | 11 · CLI auth |
| `Briefing.dc.html` | 12 · Briefing — clean (repo folder) |

## 12 · Briefing — clean

Cleanup of the repo briefing tab, using only today's data and actions:

- Left section index (01–08) with one status glyph each — ● pinned, ◐ hybrid, ○ auto — instead of a badge on every card.
- One reading column (~820px), no box around each section; numbered heading + thin neon rule.
- Per-section description and the long "Last edit: … (via MCP) — …" line collapse to one short meta line (`agent_mcp · 9/28/2026`).
- Overview: `purpose` as a larger lead sentence, `description` as short paragraphs.
- Architecture: `data_flow` split on `->` into step chips per pipeline; `components` as a Name / Role / Path table.
- Remaining sections start collapsed as one-line rows (new interaction: click to expand).
- "Clear & regenerate" demoted to a quiet button; Notion sync status moved into the toolbar.
