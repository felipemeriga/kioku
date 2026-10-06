Kioku (記憶, "memory") is a second brain for your repos. The interface is **cyberpunk 80s Japan**: neon magenta and electric cyan on a deep purple-black, CRT scanlines, kanji accents — kept dense and calm enough to work in all day. Everything is dark mode; there is no light theme.

## Content fundamentals

- **Voice**: a terse, competent tool talking to a developer. Short sentences, no exclamation marks, no emoji. Second person when guiding ("Ask your second brain."), impersonal for status ("Full reconciliation started.").
- **Casing**: sentence case everywhere — buttons ("Clear & regenerate", "Chat with this folder"), tabs, titles. ALL CAPS only through the `overline` style (HUD labels like `FOLDER DETAIL`, `CONVERSATIONS`).
- **Errors** start with "Couldn't …" and name the thing: "Couldn't load documents.", "Couldn't start the sync." Network failures say what to check: "Couldn't reach the sign-in service. Check your internet connection."
- **Success** is past tense and specific: "Copied to clipboard.", "Disconnected. Docs kept in the folder."
- **Commands and identifiers** go in code: `kioku init`, `kioku init --force`, filenames, SHAs. Set them in `mono`.
- **Progress copy** uses the ellipsis and the agent's stage: "Searching documents & code...", "Generating response...".
- Kanji is an accent, never content: the 記 mark, キオク furigana over the wordmark, 記憶 in the title.

## Visual foundations

### Color
- Ground is `ink`; raised surfaces are `surface` (Paper, tooltips) and `gradient-card` (Card: `surface` → `surface-2`); inputs and drawers sink to `surface-2`.
- `magenta` is the brand and the primary action: contained buttons (`gradient-cta`), the focused input border, the selected nav row, the active tab indicator. One primary action per view.
- `cyan` means **AI / scanning**: AI chips, the Inspect button, retrieval states, text selection (`cyan` at 33%), the logo's scan ticks.
- `purple` (legacy name `violet-2`) is the third accent — gradient bridge and the third color in sets of three (briefing section icons rotate `cyan` → `magenta` → `purple`).
- Status: `green` success, `amber` warning/stale, `red` error. Always pair status color with a word or icon.
- Tints come from hex-alpha suffixes on brand colors, not new tokens: hover washes at `10`–`14` (6–8%), selected fills at `22` (13%), borders at `33`–`55`, glows at `44`–`66`. In code: `` `${brand.magenta}22` `` or MUI `alpha(brand.magenta, 0.13)`.
- Text: `text` for primary, `muted` for secondary (6.3:1 on `ink`), `dim` only for 24px+ or non-essential hints (3.2:1 — fails AA for body copy).
- Borders: `line` hairlines (1.3:1, decorative), `line-glow` on hover, `magenta` on focus. Don't let `line` be a control's only boundary.
- The `tw-*` and `panel-*` colors are literals hard-coded in components (Tailwind emerald/red/amber/blue/violet/cyan and three neutral greys). They are documented so you can match the current UI; new work should use the brand tokens (e.g. `green` over `tw-emerald-500`, `surface` over `panel-121219`).

### Type
- One family does almost everything: **Rubik** (`display` and `body`), with Noto Sans JP as the kanji fallback. Headings `h4`–`h6` at 600–700 with slight negative tracking; body `body1`/`body2` at 1.55 line height.
- **JetBrains Mono** (`mono`) is the HUD voice: `overline` labels (0.22em tracking, uppercase), every Chip, SHAs, model names, counts (`mono-caption`).
- Buttons and tabs use `button`: Rubik 600, sentence case, never uppercase.
- Fonts load from Google Fonts: Rubik 300–900, JetBrains Mono 400–600, Noto Sans JP 300–900.

### Space, shape, depth
- MUI's 8px grid: `space-0.5` … `space-4`. Cards and dialogs pad `space-2`; pages `space-3`.
- Corners are tight — "cyberpunk hardware, not consumer app": `radius-sm` (4px) is the base for buttons, inputs, tooltips; `radius-xs` (3px) for chips, icon buttons and nav rows; `radius-md` (8px) for document and status cards; `radius-lg` (12px) for chat bubbles and briefing sections. `radius-pill` only for dots.
- Depth is glow, not grey shadow: `shadow-cta` under contained buttons, `shadow-focus` on focused inputs, `glow-1`/`glow-2`/`glow-3` (`neonGlow(hex, n)`) for hero surfaces. `shadow-paper` is the one dark drop shadow, for floating Paper.

### Atmosphere
- The page body carries two ambient blooms — `magenta` at 13% top-left, `cyan` at 9% bottom-right — over `scanlines`, fixed to the viewport. Don't add more blooms inside panels.
- Scrollbars: 10px, `line` thumb on `ink-deep`, magenta on hover.
- Motion is short and functional: the ThinkingBar's segment sweep, ingestion dots, glow intensifying on hover. No decorative animation.

### Focus and states
- Focused inputs: `magenta` border + `shadow-focus`. Hover: `line-glow` border or a 6–8% magenta wash. Selected rows: 13% magenta fill with a 2px `magenta` left edge.
- Disabled: MUI default opacity; no color change of its own.

## Iconography
- **Material Icons** (`@mui/icons-material`) for all UI — filled by default, `Outlined` variants inside the briefing. Sizes 16–20px in dense rows, 24px default. Icons take the accent of their context (`cyan` for AI, `magenta` for brand actions) or `muted`.
- Integration marks — `GitHubBrandIcon`, `NotionBrandIcon`, `Mem0BrandIcon` — are SvgIcons tinted by `currentColor`, used only beside their integration's name. The Mem0 mark is an approximation (their SVG isn't open).
- File types map to an icon + color in DocumentCard: pdf `tw-red-500`, docx `tw-blue-500`, md `tw-emerald-500`, html `tw-amber-500`, txt white at 50%.
- The logo is the **hanko** (`assets/Logos/kioku-hanko.svg`): an `ink` tile with a magenta→cyan gradient frame, a glowing 記 and cyan scan ticks. It's the favicon and sits in the IconRail beside the `KIOKU` wordmark (Rubik, with キオク above). No emoji anywhere.

## Using the components
- `window.Kioku` holds the app's real components (frontend/src), each already wrapped in `Kioku.Provider` (theme, router, auth, toasts, conversations) and fed demo data offline. Screens (`ChatPage`, `DocumentsPage`, `FolderDetailPage`, `SettingsPage`, `LoginPage`, `CliAuthPage`) render the App.tsx route tree at a path.
- For new UI, compose `Kioku.mui.*` inside `Kioku.Provider` — the theme overrides apply automatically — and reach for `Kioku.brand`, `Kioku.fonts`, `Kioku.neonGlow` instead of literals.

## Not synced
- **Fonts**: hosted on Google Fonts, so no font files were copied — `type.families` names them and previews load them from Google.
- **Theme helpers as values**: `neonGlow()` is captured at magenta in `glow-1…3`; other hexes need the function.
- **Components** are bundled from source with an offline mock of `/api` and Supabase (`lib/api.ts` runs unchanged against fixtures). Real data, uploads, auth and streaming need the deployed app. DocumentViewerDrawer ships a light Prism build here (8 languages) instead of the app's lazy-loaded full one.
- **Providers** (`AuthProvider`, `ConversationsProvider`, `ProtectedRoute`) have no card — they live inside `Kioku.Provider`.
