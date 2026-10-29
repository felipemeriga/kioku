# Repository learnings: calendar and timeline

The repository's **Learnings** tab has two views. **Journal** answers “what happened on this day?” from the original Markdown. **Learnings** shows Mihari's small, current set of source-linked conclusions.

## Layout

```text
Project memory                               Journal | Learnings
┌ Calendar, 310px ┐  ┌ Selected day / Markdown toggle ──────┐
│ October 2026  ‹ ›│  │ 10:15  ● Codex                       │
│ M T W T F S S    │  │ Finding and outcome, rendered as MD  │
│ · · 27 28 · · ·    │  │ 13:40  ● Claude Code                 │
│ ● Claude ● Codex │  │ Next entry, source preserved         │
└──────────────────┘  └────────────────────────────────────────┘
```

The calendar becomes a full-width block above the timeline below 800px. The folder navigator stays in the app's left rail. Each day has the two possible agent dots; a day without a dot has no journal. The selected day has a magenta outline. The timeline uses a real vertical rule because entries are chronological, with agent-specific dots and no decorative numbering.

## Tokens

Use the existing `frontend/src/theme.ts` palette: `ink` `#070510` for the page, `surface` `#12091F` for reading containers, `surface2` `#0D0718` for source Markdown, `line` `#654B83` for structure, `text` `#FAF7FF`, `muted` `#E0D5F3`. Magenta `#FF1493` marks Claude and selection; cyan `#00F0FF` marks Codex and the learning card edge. IBM Plex Sans carries prose; IBM Plex Mono carries source text, times and SHAs. Paragraphs stay below 80 characters where possible.

## Behavior

- On first open, show the latest recorded day in the selected year. Moving between months never fabricates activity.
- Clicking a marked or empty date changes the reader. Empty dates say that there was no recorded interaction.
- The **Markdown** toggle shows the exact stored file, including metadata; the default timeline renders its entries for reading.
- Each learning links to its source day. **Agent report** means an agent described it; **On main** requires the cited full SHA to be present on the principal branch. Neither label asserts a deployment.
- Loading, error and empty states occupy the reading surface. Keyboard focus is cyan and motion is limited to interaction feedback.
