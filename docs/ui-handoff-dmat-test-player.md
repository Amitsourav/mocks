# UI hand-off — dMAT test player (AvM-UI)

Build the **test-taking experience** for the dMAT full mock. The backend APIs are
live. This is a **linear, single-choice** exam: one continuous Next/Back sequence of
**76 questions** (Figure Sequences 20 → Mathematical Equations 20 → Latin Squares 16 →
General Academic 20), one overall countdown that **auto-submits at 0**. Answers are
**saved but not scored** — on submit we show a "we're checking your answers" message and
return to the catalog (no results screen yet).

Repo: `AvM-UI` (Next.js 15 App Router, React 19, TS, Tailwind v4, shadcn). Reuse the
existing `lib/api.ts` fetch wrapper (Supabase JWT `Authorization: Bearer`), design tokens,
`formatDuration`, and the Modal pattern.

---

## 1. Backend API contracts (all require `Authorization: Bearer <supabase jwt>`)

Base URL = `process.env.NEXT_PUBLIC_API_BASE_URL`.

### Start an attempt (freezes a random 76-question paper)
`POST /exams/{examination_id}/attempts` → **201**
```jsonc
// AttemptState
{ "id": "uuid", "examination_id": "uuid", "status": "in_progress",
  "started_at": "...", "submitted_at": null, "expires_at": "...",
  "current_section_id": null, "sections": [ /* per-section state, not needed for the linear player */ ] }
```
`409 {detail:{code:"attempt_already_active"}}` if the user already has one in progress → resume it (see current-attempt).

### Resume helper
`GET /exams/{examination_id}/attempts/current` → **200** `AttemptState` (the in-progress
attempt) **or 404 `{code:"no_active_attempt"}`**.

### Get the whole paper (call after start/resume, and on reload)
`GET /attempts/{attempt_id}/paper` → **200**
```jsonc
// PaperOut  — NO correct-answer fields are ever present
{
  "attempt_id": "uuid", "exam_code": "dMAT", "status": "in_progress",
  "expires_at": "2026-07-21T...Z", "server_time": "...Z", "remaining_seconds": 12592,
  "total_questions": 76,
  "sections": [ {"code":"FIGSEQ","name":"Figure Sequences","count":20},
                {"code":"MATHEQ","name":"Mathematical Equations","count":20},
                {"code":"LATSQ","name":"Latin Squares","count":16},
                {"code":"GENACAD","name":"General Academic Module","count":20} ],
  "questions": [
    {
      "id": "uuid",
      "section_code": "FIGSEQ", "section_name": "Figure Sequences",
      "position": 1,                       // 1..76, already in exam order
      "question_type": "single_choice",
      "content_md": "…markdown + $LaTeX$ + inline ![](data:image/png;base64,…) …",
      "stimulus_md": null,                 // General Academic items carry a shared passage here
      "options": [ {"id":"uuid","label":"A","content_md":"…","position":1}, … 4 total ],
      "selected_option_id": null,          // the user's saved pick (for resume) or null
      "is_marked_for_review": false
    }
    // … 76 questions in `position` order
  ]
}
```

### Save one answer (autosave on each selection)
`POST /attempts/{attempt_id}/answers`
```jsonc
// body — dMAT is single-choice, so send selected_option_id only
{ "question_id": "uuid", "selected_option_id": "uuid", "is_marked_for_review": false }
```
→ **200** `{ "saved": true, "attempt_id", "question_id", "answered_at" }`.
`409 {code:"attempt_expired"}` if the overall time is over (reject silently / stop the timer).

### Submit
`POST /attempts/{attempt_id}/submit` → **200**
```jsonc
{ "status": "submitted",
  "message": "We're checking your answers — we'll let you know once your result is ready." }
```
No scoring happens. Show the message, then return to the mock catalog.

---

## 2. `lib/api.ts` + `lib/types.ts` additions

Types (`lib/types.ts`):
```ts
export type PaperOption = { id: string; label: string | null; content_md: string; position: number };
export type PaperQuestion = {
  id: string; section_code: string; section_name: string; position: number;
  question_type: string; content_md: string; stimulus_md: string | null;
  options: PaperOption[]; selected_option_id: string | null; is_marked_for_review: boolean;
};
export type PaperSection = { code: string; name: string; count: number };
export type Paper = {
  attempt_id: string; exam_code: string; status: string;
  expires_at: string | null; server_time: string; remaining_seconds: number;
  total_questions: number; sections: PaperSection[]; questions: PaperQuestion[];
};
export type AttemptState = { id: string; examination_id: string; status: string; expires_at: string | null };
```
Functions (`lib/api.ts`, mirror the existing wrapper style):
```ts
startAttempt(examinationId): POST /exams/{examinationId}/attempts        -> AttemptState   (may throw ApiError 409 attempt_already_active)
getCurrentAttempt(examinationId): GET /exams/{examinationId}/attempts/current -> AttemptState (throws 404 no_active_attempt)
getPaper(attemptId): GET /attempts/{attemptId}/paper                     -> Paper
saveAnswer(attemptId, { question_id, selected_option_id }): POST /attempts/{attemptId}/answers -> { saved: true }
submitAttempt(attemptId): POST /attempts/{attemptId}/submit              -> { status, message }
```

---

## 3. Launch wiring (from the mock catalog)

`GET /mock-tests` now returns `examination_id` on each mock (non-null only for the playable
dMAT full mock, where `is_playable === true`).

- `components/app/mocks/MockCard.tsx`: today "Start test" is hard-wired to `openComingSoon`.
  For a mock with `is_playable && examination_id`, wire it to **launch the exam** instead
  (add an `onStart(examinationId)` prop or a context action, e.g. `openExam`). Keep the
  coming-soon gate for every non-playable mock.
- Add a third app view. `components/app/Sidebar.tsx` `AppView = "dashboard" | "mocks"` →
  add `"exam"`; `AppShell.tsx` switch renders `<ExamPlayer examinationId=…/>` full-screen
  (no sidebar) when active.

**Start/resume sequence** when the exam view opens:
1. `getCurrentAttempt(examinationId)` → if it resolves, you have an in-progress attempt
   (optionally show a "Resume your test?" confirm). If it 404s, `startAttempt(examinationId)`
   (handle 409 by falling back to `getCurrentAttempt`).
2. `getPaper(attempt.id)` → render.

---

## 4. Content rendering (NEW — nothing renders Markdown/LaTeX/images today)

Add deps: `react-markdown remark-math rehype-katex remark-gfm katex`. Import
`katex/dist/katex.min.css` once (e.g. in `app/layout.tsx`).

Create one reusable `<QuestionContent md={string} />`:
```tsx
<ReactMarkdown remarkPlugins={[remarkMath, remarkGfm]} rehypePlugins={[rehypeKatex]}
  components={{ img: (p) => <img {...p} className="max-w-full" alt={p.alt ?? ""} /> }}>
  {md}
</ReactMarkdown>
```
- **Math**: `$…$` inline, `$$…$$` block (e.g. `$$\begin{cases}…\end{cases}$$`) → KaTeX.
- **Images**: Figure-Sequence questions embed `![seq](data:image/png;base64,…)` inline — they
  render as `<img>` with **no network** needed. Options may also be images.
- **Tables**: Latin-Square questions use Markdown tables → needs `remark-gfm`.
Use `<QuestionContent>` for the stem, the `stimulus_md` (if present), and each option's
`content_md`.

---

## 5. The exam player

- **Header bar**: current `section_name` (changes as `position` crosses into a new section) ·
  `Question {position} of 76` · **countdown**. Compute the end time once from the paper:
  `endAt = Date.now() + remaining_seconds*1000`; tick every second, format `H:MM:SS`.
  When it reaches 0 → **auto-submit** (call submit, go to the interstitial).
- **Body**: `<QuestionContent>` for stimulus (if any) + stem, then the 4 options as
  selectable cards (single choice, radio semantics). Highlight the chosen one.
- **On select**: set local `selected_option_id` immediately (optimistic) and fire
  `saveAnswer(attemptId, {question_id, selected_option_id})` (don't block the UI; ignore
  benign failures, but if it returns 409 `attempt_expired`, stop the timer and move to submit).
- **Footer**: `Back` (disabled at Q1) · `Next` (disabled at Q76) · a `Submit` button
  (always available). Optional **question palette**: a grid of 1..76 chips coloured
  answered / not-answered / marked-for-review, click to jump; group by section.
- **Submit**: confirm modal ("You've answered X of 76. Submit?") → `submitAttempt` →
  full-screen **interstitial** showing the returned `message`
  ("We're checking your answers — we'll let you know…") with a calm spinner, then a button
  to return to the Mock catalog. **No results screen** (scoring is a later feature).
- **Resume**: `getPaper` already returns each question's `selected_option_id` and the
  remaining time, so restoring state is just reading the paper.

---

## 6. Integrity — tab-switch / focus / fullscreen (backend is ready)

You **cannot truly block** a user from switching tabs or apps — the browser/OS owns that.
The realistic approach is **fullscreen + detect + log + deter**, and the backend already
accepts the integrity events. Post them via `POST /attempts/{attempt_id}/events`:
```jsonc
{ "events": [ { "event_type": "focus_lost",   "client_occurred_at": "…Z" },
              { "event_type": "focus_regained","client_occurred_at": "…Z" },
              { "event_type": "fullscreen_exit","client_occurred_at": "…Z" },
              { "event_type": "fullscreen_enter","client_occurred_at": "…Z" } ] }
```
(Only these four integrity `event_type`s are valid for this; anything else is rejected.)

Implement in the exam player:
1. **Enter fullscreen on start**: `document.documentElement.requestFullscreen()` (needs a user
   gesture — trigger it from the "Start test" / "Begin" click). Show a "Start in fullscreen"
   button if the browser blocks the auto-request.
2. **Detect leaving**:
   - `document.addEventListener("visibilitychange")` → `document.hidden` true = tab hidden →
     post `focus_lost`; false = `focus_regained`.
   - `window.addEventListener("blur"/"focus")` as a secondary signal (switching apps/windows).
   - `document.addEventListener("fullscreenchange")` → not in fullscreen = post `fullscreen_exit`
     (and re-prompt to re-enter); back in = `fullscreen_enter`.
3. **Deter — LOCKED POLICY: 2 warnings, then close on the 3rd.**
   - A **violation** = the student leaves the test: tab hidden (`visibilitychange`→hidden),
     window blurred, or fullscreen exited. **Debounce** so one physical action counts once
     (e.g. ignore a repeat within ~800 ms, and don't double-count a fullscreen-exit that
     rides along with a tab-hide).
   - Keep a local `violations` counter (also persist it on the attempt in memory so a reload
     mid-test can rehydrate from the logged events if you want — optional).
   - **Violation 1 →** warning modal: *"You left the test. This is recorded. Warning 1 of 2 —
     leaving again twice will end your test."*
   - **Violation 2 →** stronger warning: *"Warning 2 of 2. One more and your test will be
     submitted automatically."*
   - **Violation 3 →** immediately call `submitAttempt(attemptId)` and go straight to the
     "we're checking your answers" interstitial (no further confirm). The test is over.
   - Always still POST the corresponding integrity event(s) for every violation (even the 3rd)
     so the server has the full record.
4. Batch the events (flush on each occurrence or every few seconds) — the endpoint takes an
   array. The count/close logic is client-side; the events are the durable server-side record.

Note: these events are **logged for integrity review**, not scored. Prevention is best-effort
(fullscreen + warnings); true lockdown needs a native/proctoring layer which is out of scope.

## 7. Constraints / notes
- dMAT is **single-choice** only — use `selected_option_id` (never multi-select/numeric here).
- **Never** expect or render a correct answer — the API doesn't send one.
- The catalog card's "90 questions / 180 min" copy is stale marketing metadata; the **paper**
  is the source of truth (76 questions, `remaining_seconds` ≈ 210 min). Show the paper's
  numbers inside the player.
- One active attempt per user+exam is enforced server-side (409) — hence the resume flow.
- Autosave is per-selection; there's no "save all" — submitting just finalises.
