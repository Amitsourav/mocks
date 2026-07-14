# Deploying to Railway

This backend deploys to [Railway](https://railway.app) as two services — the
**FastAPI app** and a **managed Redis** — while Postgres, Auth, and Storage stay
on **Supabase**. You do **not** add a Railway Postgres; the database lives on
Supabase and the app connects to it via the Supavisor pooler.

```
Railway project
├── backend service  (this repo's Dockerfile)  ──► Supabase Postgres (mock_db)
│                                                ──► Supabase Auth / Storage
└── Redis            (Railway managed)          ◄── backend REDIS_URL
```

---

## 1. Add Redis

1. In your Railway **project**: **New → Database → Add Redis**.
2. Railway provisions a managed Redis and exposes `REDIS_URL` (public proxy) and
   `REDIS_PRIVATE_URL` (internal network) on the Redis service.

Prefer the **private** URL for app→Redis traffic (stays inside Railway, no
egress cost). You reference it from the backend service in step 3.

## 2. Deploy the backend

1. Push this repo to GitHub.
2. In the Railway project: **New → Deploy from GitHub repo**, pick this repo.
3. Railway detects the **Dockerfile** and builds it. No Procfile/start command
   needed — the Dockerfile runs uvicorn on Railway's injected `$PORT`
   (`--port ${PORT:-8000}`).

## 3. Set backend variables

On the **backend service → Variables**, add the following. Use Railway's
**reference variable** syntax (`${{Redis.REDIS_PRIVATE_URL}}`) for Redis so it
auto-fills and survives credential rotation.

```
APP_ENV=production
LOG_LEVEL=INFO

# Database — Supabase Transaction pooler (port 6543), from
# Supabase → Project Settings → Database → Connection string → "Transaction"
DATABASE_URL=postgresql://postgres.lqcmhzouantgqrxlurhm:PASSWORD@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres

# Supabase
SUPABASE_URL=https://lqcmhzouantgqrxlurhm.supabase.co
SUPABASE_PROJECT_REF=lqcmhzouantgqrxlurhm
SUPABASE_JWT_SECRET=<Supabase → Project Settings → API → JWT Secret>
SUPABASE_JWT_ALG=HS256
SUPABASE_JWKS_URL=https://lqcmhzouantgqrxlurhm.supabase.co/auth/v1/.well-known/jwks.json

# Redis — reference the Railway Redis service (private network preferred)
REDIS_URL=${{Redis.REDIS_PRIVATE_URL}}

# CORS — your FRONTEND URL(s), comma-separated. NOT the backend's own URL.
CORS_ORIGINS=https://your-frontend-domain.com

# Storage
STORAGE_BUCKET=exam-media
SIGNED_URL_TTL=3600
```

Notes:
- **`DATABASE_URL`** uses the **Transaction pooler (6543)**, not the direct
  connection — matches the `statement_cache_size=0` setting in `app/core/db.py`.
- **`REDIS_URL`** must be the `${{Redis.REDIS_PRIVATE_URL}}` reference, not a
  hardcoded string and not `localhost`.
- **`CORS_ORIGINS`** is the browser-facing frontend origin(s); exact scheme +
  domain + port, no trailing slash.
- **`PORT`** is set by Railway automatically — do not set it yourself.

## 4. Networking / health checks

- Railway assigns a public domain to the backend service (Settings → Networking →
  Generate Domain), e.g. `https://your-backend.up.railway.app`.
- Set the **health check path** to `/health` (Settings → Health Check) so Railway
  only routes traffic to healthy instances. Use `/health/ready` if you want the
  deploy to wait on Postgres + Redis being reachable.

## 5. Scaling to concurrency

- Increase **replicas** on the backend service to run multiple stateless
  instances behind Railway's load balancer (matches the D5 autoscaling design).
- Because sessions live in Postgres + Redis (never in-process), any replica can
  serve any request.
- Keep an eye on Supabase's connection limit: each replica opens up to
  `DB_POOL_MAX` pooled connections. The Supavisor transaction pooler multiplexes
  these, but keep `DB_POOL_MAX` modest (default 10) and scale replicas within the
  project's pooler ceiling.

## 6. First-deploy checklist

- [ ] Redis service added; `REDIS_URL=${{Redis.REDIS_PRIVATE_URL}}` on backend
- [ ] `DATABASE_URL` = Supabase **transaction pooler** string (real password)
- [ ] `SUPABASE_JWT_SECRET` set
- [ ] `CORS_ORIGINS` = real frontend origin(s)
- [ ] Public domain generated; health check path `/health`
- [ ] Migrations already applied to Supabase (`migrations/0001–0003`) — they run
      against Supabase, not Railway
- [ ] Twilio configured in **Supabase Auth** (Dashboard → Authentication →
      Phone) — not in Railway env; India go-live also needs DLT/TRAI templates
- [ ] Hit `GET /health/ready` on the Railway domain → `postgres: ok`, `redis: ok`
