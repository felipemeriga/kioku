# Kioku web app

React/TypeScript workspace for chat, documents, repository details, journals,
learnings, integrations, remotes, and settings. Uses MUI, TanStack Query, and Vite.

## Run locally

Follow [backend/database setup](../docs/development.md), then:

```bash
cp .env.local.example .env.local
# Set local VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.
npm ci
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` to `http://localhost:8000`.
Only public Supabase values belong in `VITE_*`; they are embedded in the bundle.

## Source map

- `src/App.tsx`: routes and shared providers.
- `src/pages/`: login, CLI authorization, chat, documents, and settings.
- `src/components/`: workspace navigation, viewers, streaming chat, and repository UI.
- `src/hooks/` and `src/lib/`: application state, API and Supabase integration.
- `src/theme.ts` and styles: current runtime visual tokens.

Native chat uses durable backend turn/job state, replay and explicit recovery.
The model picker reads the authenticated subscription catalog; stale/unavailable
states are meaningful and should not be replaced by a fabricated model list.
The original transcript viewer in open PR #214 is not part of this main snapshot.

## Validate

```bash
npx eslint .
npx tsc --noEmit
npm run test:run
npm run build
```

CI supplies placeholder Supabase environment values for unit tests. Build output
is `dist/`; production Nginx handles SPA routes and backend proxying. Changing
public environment values requires rebuilding.

See [design guidance and previews](../design-system/README.md),
[architecture](../docs/architecture.md), and [documentation index](../docs/README.md).
