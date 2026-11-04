# Kioku design system

Use the running frontend as the implementation reference. The current visual
system is Neon Tokyo: saturated magenta/cyan accents, opaque dark reading surfaces,
and restrained interactive edges. Historical preview bundles in this directory
are offline snapshots and may differ from current components.

## Current runtime foundations

`frontend/src/theme.ts` owns the current palette, typography, theme overrides,
status glyphs, and glow helpers. `frontend/src/fidelity.css` and component styles
also affect the rendered app. Prefer exported tokens over new literals.

| Role | Current value |
| --- | --- |
| Primary / magenta | `#FF1493` |
| AI / cyan | `#00F0FF` |
| Background / ink | `#070510` |
| Surface | `#12091F` |
| Recessed surface | `#0D0718` |
| Primary text | `#FAF7FF` |
| Secondary text | `#E0D5F3` |
| Body/display | IBM Plex Sans with Noto Sans JP/system fallbacks |
| Code and metadata | IBM Plex Mono with system monospace fallbacks |

Scanlines are disabled in the current theme. Older Rubik/JetBrains Mono token
exports and glass/CRT previews describe previous snapshots, not new UI requirements.

## Content and interaction

Use sentence case, short specific messages, and developer-facing identifiers in
monospace. Describe errors with the failed action and a useful recovery step.
Status color needs text or an icon. Keep one clear primary action per view and
preserve keyboard focus, readable contrast, and narrow-screen reading behavior.

## Preview library

`components/*/README.md` describes the adjacent bundled/offline component preview.
Some explicitly pin an older source revision. `window.Kioku`, fixture data, and
preview providers belong to those preview bundles; they are not a public runtime
API of the application. Check `frontend/src/` before copying props or behavior.

`tokens.json`, `tokens.css`, assets, and `mockups/neo-tokyo/` are design/reference
artifacts. They do not automatically regenerate from the current MUI theme.
The LearningsTimeline preview documents journals/learnings; the transcript reader
in open PR #214 remains pending. See [change status](../docs/change-status.md).

[Frontend guide](../frontend/README.md) · [documentation index](../docs/README.md)
