# Frontend Integration Guide — dMAT Platform

Everything the frontend needs. The frontend talks to **two** systems:

1. **Supabase** — login via OTP (phone or email). Issues a JWT (access token).
2. **This backend** — all exam data (exams, attempts, answers). Verifies the JWT.

The backend never sends OTPs and never sees passwords. It only checks the token.
Switching login method (phone vs email) changes nothing on the backend — same token.

---

## 1. Config values

```
SUPABASE_URL   = https://lqcmhzouantgqrxlurhm.supabase.co
SUPABASE_KEY   = sb_publishable_txo8kGzUpyQ47l2C4ij-0A_P47vVFxg   # publishable — safe in frontend
BACKEND_URL    = http://localhost:8000                            # local dev (deployed URL TBD)
```

Create one Supabase client (install `@supabase/supabase-js`):
```js
import { createClient } from '@supabase/supabase-js'
export const supabase = createClient(SUPABASE_URL, SUPABASE_KEY)
```

---

## 2. Login screen — ONE screen, email OR phone

The user picks one method; the OTP goes to whichever they filled. Recommended
layout: an Email/Phone toggle over a single input (avoids "user filled both").

```
┌─────────────────────────┐
│  [ Email ]  [ Phone ]   │  ← toggle
│  ┌───────────────────┐  │
│  │ you@email.com     │  │  ← field swaps with the toggle
│  └───────────────────┘  │
│  [   Send code   ]      │
└─────────────────────────┘
```

Input validation:
- Email path: value contains `@`.
- Phone path: E.164 — `+91` then the 10 digits, no spaces (e.g. `+917004428198`).

### Step 1 — send the code (branch on method)
```js
async function sendOtp({ method, email, phone }) {
  if (method === 'email') await supabase.auth.signInWithOtp({ email })
  else                    await supabase.auth.signInWithOtp({ phone })
}
```

### Step 2 — verify the 6-digit code (use the same method)
```js
async function verify({ method, email, phone, code }) {
  const params = method === 'email'
    ? { email, token: code, type: 'email' }
    : { phone, token: code, type: 'sms' }
  const { data, error } = await supabase.auth.verifyOtp(params)
  if (error) throw error
  return data.session   // data.session.access_token → use for the backend
}
```

Track which method the user chose so `verify` sends the right params. After
verify, both paths are identical.

> **Email must be a code, not a link.** By default Supabase emails a magic *link*.
> For the 6-digit code UX above, the "Magic Link" email template must include
> `{{ .Token }}`. (Backend-side dashboard setting — ask the backend owner to set it.)

---

## 3. Calling the backend

Attach the token on every request:
```js
const { data: { session } } = await supabase.auth.getSession()

const res = await fetch(`${BACKEND_URL}/exams`, {
  headers: { Authorization: `Bearer ${session.access_token}` }
})
```
No valid token → every protected endpoint returns **401**.

### Token refresh — CRITICAL
Tokens expire after **1 hour**, but a dMAT attempt runs up to **3.5 hours**.
Read the session before each call (as above) so the Supabase client auto-refreshes.
Do NOT cache one token for the whole session or students get logged out mid-exam.

---

## 4. Endpoints

All require `Authorization: Bearer <token>` except `/health`.

| Method | Path | Purpose |
|---|---|---|
| GET  | `/health` | Liveness (no auth) |
| GET  | `/me` | Current user profile |
| POST | `/me/profile` | Fill the cascading registration form (see §5a) |
| GET  | `/reference/states` | States/UTs for the registration dropdown |
| GET  | `/reference/countries` | Study-destination countries |
| GET  | `/reference/mock-categories` | Top-level mock categories |
| GET  | `/reference/mock-categories/{category_code}/exams` | Exams under a category (dependent dropdown) |
| GET  | `/exams` | List active exams |
| GET  | `/exams/{exam_id}` | Exam structure + capability flags |
| POST | `/exams/{exam_id}/attempts` | Start an attempt (needs completed profile) |
| GET  | `/attempts/{attempt_id}` | Attempt state + sections (correct order) |
| POST | `/attempts/{attempt_id}/sections/{section_id}/enter` | Enter section, get questions |
| POST | `/attempts/{attempt_id}/answers` | Submit/update one answer |
| POST | `/attempts/{attempt_id}/events` | Batch timing/integrity events |
| POST | `/attempts/{attempt_id}/sections/{section_id}/submit` | Finish a section |
| POST | `/attempts/{attempt_id}/submit` | Submit the whole attempt |

Interactive reference (try every endpoint live): **`{BACKEND_URL}/docs`**

---

## 5. App flow

```
1. Login screen        -> email OR phone OTP -> session (access_token)
2. GET /me             -> if profile_completed == false, show registration form (§5a)
3. POST /me/profile    -> cascading selections + name + phone
4. GET /exams          -> list; pick dMAT
5. GET /exams/{id}     -> show modules -> sections; capability flags drive the UI
6. POST /exams/{id}/attempts        -> start; returns attempt + sections in order
7. Per section, IN ORDER:
     POST .../sections/{sid}/enter  -> render questions + per-section timer
     POST .../answers               -> on each answer (upsert)
     POST .../events                -> question_viewed, focus_lost, etc.
     POST .../sections/{sid}/submit -> when done / time up
8. POST /attempts/{id}/submit       -> finish
```

### 5a. Registration form (the cascade)

After login, if `GET /me` returns `profile_completed: false`, show the registration
form. It's a **dependent cascade** — each selection loads the next dropdown from
the reference endpoints (all require the session token):

```
1. Full name         (text)
2. Phone             (E.164, e.g. +919876543210) — required even for email login
3. State             GET /reference/states                 -> pick a state code
4. Mock category     GET /reference/mock-categories        -> pick a category code
5. Exam name         GET /reference/mock-categories/{categoryCode}/exams
                                                           -> pick a catalog_exam code
6. Target country    only if the chosen exam has requires_country == true;
                     GET /reference/countries. If the exam has a
                     default_country_code (e.g. d-MAT -> DE) you may preselect it.
```

Each reference item is `{ code, name, ... }` — **submit the `code`, display the
`name`.** The exams response also carries `requires_country` and
`default_country_code` so the form knows whether to show the country step.

Submit:
```js
await fetch(`${BACKEND_URL}/me/profile`, {
  method: 'POST',
  headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({
    full_name, phone,                 // phone is E.164
    state_code, mock_category_code, catalog_exam_code,
    target_country_code               // omit/null when the exam needs no country
  })
})
```

The backend **validates every code** against the catalog and checks the exam
belongs to the chosen category. Validation errors return `422` with
`{ detail: { code, message } }` — e.g. `invalid_phone`, `invalid_state`,
`exam_category_mismatch`, `country_required`. Surface `detail.message` inline.

### Rules the backend enforces (mirror in UX)
- **Sections must be entered in order** → out-of-order = `409 section_out_of_order`.
- **Per-section timer is server-authoritative** → `enter` returns `deadline_at` +
  `remaining_seconds`; answers after the deadline = `409 section_expired`.
- **Overall attempt clock** (`expires_at`) → after it passes, `409 attempt_expired`.
- **Answer keys are never sent** → question payloads omit correct answers by design.

### Answer payload (`POST .../answers`)
```json
{ "question_id": "uuid", "selected_option_id": "uuid", "is_marked_for_review": false }
```
(For multi-select use `selected_option_ids: [uuid]`; for numeric use `numeric_answer`.)

### Error shape
```json
{ "detail": { "code": "section_out_of_order", "message": "Finish the previous section first." } }
```
Auth errors: `401` with `{ "detail": "..." }`.

---

## 6. Environment notes

- **Local only right now.** `http://localhost:8000` works for a frontend on the
  same machine. A phone/other device on the same WiFi uses the machine's LAN IP.
  A hosted frontend needs the backend deployed (see `docs/deploy-railway.md`).
- **CORS** currently allows localhost ports 3000/3001/5173/5174/8080. A different
  dev-server port must be added to the backend's `CORS_ORIGINS`.
- **Capability flags** on `GET /exams/{id}` (e.g. `allows_revisit_within_section`,
  `section_navigation_locked`, `has_negative_marking`) tell the UI how this exam
  behaves — drive the exam-runner UI from these, not hardcoded assumptions.
