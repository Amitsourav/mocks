-- ============================================================================
-- Migration 0012 — per-attempt frozen question set (the "paper")
-- When a student starts an attempt we sample a real-exam-sized set of questions
-- per section (dMAT: 20/20/16/20 = 76) from the larger bank and FREEZE it here,
-- with a linear position. This makes next/back navigation and submission stable
-- and scoped to exactly what the student was shown. Same RLS posture as the rest
-- of mock_db (enabled, no policies — backend service role serves).
-- ============================================================================

create table if not exists mock_db.attempt_questions (
  id          uuid primary key default gen_random_uuid(),
  attempt_id  uuid not null references mock_db.attempts(id) on delete cascade,
  question_id uuid not null references mock_db.questions(id) on delete cascade,
  section_id  uuid not null references mock_db.exam_sections(id),
  position    int  not null,                         -- linear order across the whole paper
  created_at  timestamptz not null default now(),
  constraint uq_attempt_questions unique (attempt_id, question_id)
);

create index if not exists idx_attempt_questions_attempt_pos
  on mock_db.attempt_questions(attempt_id, position);

alter table mock_db.attempt_questions enable row level security;
