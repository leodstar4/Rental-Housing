# Renta MX — frontend

TanStack Start + React 19 + Tailwind v4 + Radix/shadcn. This directory is the **source of
truth** for the Renta MX (and legacy US) web app. It is a monorepo folder inside
`rental-housing-navigator`; the backend lives in `../mx` + `../api`.

> **Lovable is only a demo.** The project started on [Lovable](https://lovable.dev) and that
> hosted preview still exists, but it is a demo mirror. Make changes here, in this repository.
> Re-sync a Lovable snapshot (if ever needed) by mirroring its export into `frontend/`.

> ⚖️ **Not legal advice.** Information prototype for the Hack-Nation × RealPage challenge.

## Layout

- `src/routes/` — pages (TanStack Router).
- `src/lib/api.ts` — typed API client; base URL from `VITE_API_BASE` (see below).
- `src/lib/mx-i18n.ts` — typed ES/EN copy.
- `src/components/mx/MxShared.tsx` — shared Renta MX components.

## Run locally

Needs [Bun](https://bun.sh) (or Node.js + npm). From this folder:

```sh
bun install          # or: npm install
bun run dev          # Vite dev server (http://localhost:3000)
bun run build        # production build (Nitro output, Cloudflare target)
bun run test         # Vitest (unit tests)
bun run lint
```

Point the UI at a local backend while developing:

```sh
# .env (not committed)
VITE_API_BASE=http://localhost:8000
```

Start the backend from the repo root with `uvicorn api.main:app --reload`. If `VITE_API_BASE`
is unset, the client falls back to the deployed API
(`https://rental-housing-navigator-api.onrender.com`).

## Deploy on Cloudflare Workers

The build target is Cloudflare via `@lovable.dev/vite-tanstack-config` (Nitro preset
`cloudflare-module`): it produces a **Worker with static assets** (SSR), not a static Pages
site. `bun run build` writes `.output/server/wrangler.json` (worker name
`leodstar4-rental-housing-frontend`) and `.wrangler/deploy/config.json`, which points
`wrangler deploy` at it. Do not remove that config.

1. Cloudflare dashboard → **Workers & Pages → Create → Import a repository** (Workers Builds),
   connected to this repository.
2. **Root directory / path:** `frontend`.
3. **Build command:** `bun install && bun run build`.
4. **Deploy command:** `npx wrangler deploy`.
5. **Build variable:** `VITE_API_BASE = https://<your-render-service>.onrender.com`. It is read
   at build time by Vite, so changing it requires a new build.
6. The site is served at `https://<worker-name>.<account>.workers.dev`. That origin is **not**
   in the backend's default CORS regex: add the exact URL to `ALLOWED_ORIGINS` on Render
   (comma-separated, no trailing slash).

Full infra notes (backend + frontend + env vars + costs): [`../docs/DEPLOY.md`](../docs/DEPLOY.md).
