# Mock Exam Platform — Backend

Backend for a universal mock-examination platform. First launch exam: **dMAT**
(Digital Master Test). See the full architecture and decision log in
`docs/architecture.md`.

## Stack

- **API:** FastAPI (Python 3.12), async
- **Database:** Supabase Postgres, schema `mock_db` (accessed via Supavisor pooler)
- **Cache / timers / rate-limit:** Redis
- **Auth:** Supabase Auth (phone OTP via Twilio); backend verifies Supabase JWTs
- **Storage:** Supabase Storage (question images → signed URLs)
- **Deploy:** Docker containers on a managed autoscaling platform

## Layout

```
app/
  main.py            # FastAPI app + lifespan (DB/Redis pools)
  core/              # config, db pool, redis, JWT security
  api/
    deps.py          # auth + current-user provisioning
    routes/          # health, me, exams (attempts next)
  schemas/           # Pydantic request/response models
migrations/          # SQL migrations (source of truth for mock_db)
  0001_init_mock_db.sql
  0002_enable_rls.sql
  0003_seed_dmat.sql
```

## Database

The schema lives in Supabase under `mock_db`. Migrations are plain SQL, applied
in order. Row-Level Security is **enabled** on every table with no client
policies — the backend connects with a privileged role that bypasses RLS, and
the frontend never touches Supabase directly. Never expose the `anon` key to
clients for `mock_db` access.

## Local development

1. `cp .env.example .env` and fill in:
   - `DATABASE_URL` — the **Transaction pooler** connection string (port 6543)
     from Supabase → Project Settings → Database.
   - `SUPABASE_JWT_SECRET` — from Supabase → Project Settings → API.
2. `pip install -e ".[dev]"`
3. Run Redis (or `docker compose up redis`).
4. `uvicorn app.main:app --reload`
5. Open http://localhost:8000/docs

Or run the whole stack: `docker compose up --build`.

## Endpoints (v1 so far)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | – | Liveness |
| GET | `/health/ready` | – | Readiness (Postgres + Redis) |
| GET | `/me` | Bearer | Current user profile |
| POST | `/me/profile` | Bearer | Fill post-signup profile form |
| GET | `/exams` | Bearer | List active exams |
| GET | `/exams/{id}` | Bearer | Exam structure + capability flags |

Attempt lifecycle (start, enter section, answer, events, submit) is the next
build phase.
