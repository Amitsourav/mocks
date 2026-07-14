# Architecture

Backend for a universal mock-examination platform. First launch exam: **dMAT**.
This document is the durable reference; the full decision log lives with the
implementation plan.

## Decisions (locked)

| # | Decision | Choice |
|---|---|---|
| D1 | Backend approach | Dedicated stateless API server + Supabase (Postgres/Auth/Storage) |
| D2 | API stack | FastAPI (Python 3.12, async) |
| D3 | Auth | Supabase Auth phone-OTP + **Twilio**; backend verifies Supabase JWT |
| D4 | Live state | Postgres (source of truth) + Redis (cache, timers, rate-limit, job broker) |
| D5 | Hosting | Managed autoscaling Docker containers + managed Redis |
| D6 | Content authoring | Bulk import now → ERP/admin UI later |
| D7 | Scoring/analytics | Deferred to a separate pipeline; raw data captured now |
| D8 | Exam delivery | Section-batch delivery + per-question timing events |
| D9 | Integrity | Basic (focus/tab/fullscreen events, one active attempt, server timer) |

## Runtime

```
Frontend → HTTPS+JWT → Load balancer → FastAPI pods (stateless, autoscaled)
                                          ├─ Supabase Postgres (mock_db) via Supavisor pooler
                                          ├─ Redis (content cache, section deadlines, rate-limit)
                                          ├─ Supabase Auth (JWT verify; OTP via Twilio)
                                          └─ Supabase Storage (images → signed URLs)
Background workers (Redis broker) → future scoring/analytics pipeline
```

Scaling to 1000 concurrent: stateless API autoscales; Redis absorbs identical
question reads; Postgres mostly takes low-frequency writes; Supavisor
transaction-mode pooling caps connections; section-batch delivery minimizes
request volume; section deadlines are server-authoritative.

## Data model (`mock_db`)

- **Identity:** `users` (1:1 with `auth.users`).
- **Exam structure:** `examinations` (capability-flag switchboard) → `exam_modules`
  → `exam_sections` (own timed level) ; `subjects` (optional taxonomy).
- **Content:** `questions` (Markdown + LaTeX), `question_options`
  (secret `is_correct`), `stimuli` (shared passages), `media_assets`
  (images in Storage → signed URLs).
- **Skills:** `skills` + `question_skill_tags` (normalized join → skill-gap SQL).
- **Raw capture:** `attempts` (retakes; one-active partial unique index),
  `attempt_sections` (server-authoritative `deadline_at`), `student_answers`
  (final answer per question), `question_events` (append-only timing + integrity).
- **Deferred:** `attempt_results` (later scoring pipeline).

### Security invariants

- RLS enabled on every table; `anon`/`authenticated` have no direct access.
  The backend connects with a privileged role (bypasses RLS); the frontend never
  talks to Supabase directly.
- The correct answer (`question_options.is_correct`, `questions.numeric_answer_key`)
  is **never** included in any student-facing response. Enforced by the
  delivery queries selecting explicit safe columns, and covered by
  `scripts/smoke_test.py` (recursive answer-key leak assertion).

## dMAT mapping

- Exam flags: single-choice only, no negative marking, blank penalty, sectional
  time limits, navigation locked, revisit-within-section, shared stimulus,
  images, math; scoring `normalised` 0–200 speed+accuracy.
- Core module → Figure Sequences (25m/20q), Mathematical Equations (25m/20q),
  Latin Squares (20m/16q); break after Core. Subject module → General Academic (90m).

## Build phases

1. ✅ Schema + RLS + dMAT seed (applied to Supabase)
2. ✅ FastAPI scaffold, JWT auth, `/me` + profile
3. ✅ Catalog endpoints; import pipeline (`scripts/import_questions.py`)
4. ✅ Exam engine (attempt lifecycle, secure section delivery, deadlines, answers, events)
5. ◻ Redis cache/rate-limit wiring beyond deadlines (partial)
6. ◻ Load test to 1000 concurrent; autoscaling config
7. ◻ (Later) scoring + skill-gap analytics pipeline; ERP/admin authoring UI
