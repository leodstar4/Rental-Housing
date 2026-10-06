# Deploy — Renta MX

How the two halves are hosted and configured. Backend on **Render**, frontend on **Cloudflare
Pages**. Everything is deterministic: the runtime makes no LLM calls and no network calls in
`mx/*.py` or `api/mx.py`.

> ⚖️ Information prototype. **Not legal advice.**

## 1. Backend — Render (`render.yaml`)

A single Python web service (`rental-housing-navigator-api`) mounting the Renta MX routes
(`/mx/*`) and the frozen US legacy routes.

- **Build:** `pip install -r requirements.txt && python -m mx.verify`.
  `mx.verify` re-checks every Renta MX requirement's literal quote against `corpus_mx` and fails
  the deploy if any quote, sha256 or text_sha256 does not match. The build no longer regenerates
  the US `out/` artifacts; the US routes are legacy and tolerant of a missing `out/`
  (see [US_LEGACY.md](US_LEGACY.md)).
- **Start:** `uvicorn api.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'`
  (`--proxy-headers` so `request.client.host` is the real client IP for the `/mx/*` rate limit).
- **Health check:** `/health` (returns 200 with `us_data: true|false`).

### Environment variables

| Var | Required | Purpose |
|---|---|---|
| `PYTHON_VERSION` | yes | pinned runtime (`3.12.10`) |
| `ALLOWED_ORIGINS` | no | extra **exact** CORS origins, comma-separated. Lovable domains and `*.pages.dev` are allowed by default via a regex; add a custom frontend domain here. |
| `MX_IP_SALT` | yes (auto) | salt for the hashed client IP stored in `/mx` signature evidence (never the plain IP). Render generates it (`generateValue: true`); keep it stable to keep evidence hashes comparable. |
| `DATABASE_URL` | no | persistent store for listings/contracts (see below). Unset = ephemeral JSON files. |

### Persistence: `DATABASE_URL`

`mx/store.py` selects the backend from `DATABASE_URL` (reported honestly by `/mx/health.store`):

| `DATABASE_URL` | Backend | `store` | Persistent? |
|---|---|---|---|
| *(unset)* | JSON files under `MX_STORE_DIR` (`out/mx_store`) | `efimero` | No — the free-plan disk is ephemeral; data is lost on every restart. |
| `sqlite:///abs/path.db` | stdlib `sqlite3` | `sqlite` | Only as long as the disk survives (still ephemeral on the free plan). |
| `postgres://…` / `postgresql://…` | `psycopg` (`psycopg[binary]==3.3.6`, lazy import) | `postgres` | Yes, when the database is managed. |

For **production**, use the Render `starter` plan **and** a Render-managed PostgreSQL instance,
wiring its Internal Database URL into `DATABASE_URL`:

```yaml
# in render.yaml, under the web service envVars:
- key: DATABASE_URL
  fromDatabase:
    name: renta-mx-db
    property: connectionString
```

The `/mx/health` `store_notice` and the UI banner adjust automatically: ephemeral backends warn
"download your record"; a persistent database says the data is kept.

### Costs

| | Render free | Render starter |
|---|---|---|
| Cost | $0 | ~$7/mo per service (plus ~$7/mo for a managed Postgres) |
| Disk | ephemeral | ephemeral (use Postgres for persistence) |
| Sleep | sleeps after ~15 min idle; first request after sleep takes ~1 min | always on |

The free plan is enough for the demo; move to starter + Postgres if listings/contracts must
survive restarts.

## 2. Frontend — Cloudflare Workers

TanStack Start, Cloudflare target via `@lovable.dev/vite-tanstack-config` (Nitro preset
`cloudflare-module`): the build is a **Worker with static assets**, deployed with
`npx wrangler deploy`. See [`../frontend/README.md`](../frontend/README.md) for the step-by-step.

- **Root directory:** `frontend`.
- **Build:** `bun install && bun run build`. **Deploy:** `npx wrangler deploy`.
- **Build variable:** `VITE_API_BASE = https://<render-service>.onrender.com` (read at build time).
- The Workers free plan covers the demo.

The site is served at `https://<worker-name>.<account>.workers.dev`. That origin is not in the
backend CORS regex (which covers Lovable, `*.pages.dev` and localhost): add the exact URL to
`ALLOWED_ORIGINS` on Render.

## 3. Why not Fly.io

As of 2026 Fly.io has **no free tier** (the earlier free allowance was removed), so a
zero-cost demo would still be billed there. Render keeps a free web plan (with sleep) and
Cloudflare Pages keeps a free static/edge plan, so Render + Cloudflare Pages is the no-cost
default; Render starter + managed Postgres is the paid, persistent upgrade.
