-- ============================================================================
-- Migration 0010 — per-question worked solutions
-- One detailed AI-authored solution per question, 1:1 with mock_db.questions.
-- Joined via question_id (unique). Same posture as the rest of mock_db:
-- RLS enabled (no policies; backend service role serves), updated_at trigger.
-- ============================================================================

create table if not exists mock_db.solutions (
  id            uuid primary key default gen_random_uuid(),
  question_id   uuid not null references mock_db.questions(id) on delete cascade,
  solution_md   text not null,                       -- step-by-step solution (Markdown + LaTeX)
  final_answer  text,                                -- the answer value / statement
  correct_label text,                                -- which option (A/B/C/D)
  model         text,                                -- AI model that authored it
  generated_by  text not null default 'ai',          -- 'ai' | 'code' | 'manual'
  status        mock_db.content_status not null default 'published',
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  constraint uq_solutions_question unique (question_id)   -- exactly one solution per question
);

create index if not exists idx_solutions_question_id on mock_db.solutions(question_id);

alter table mock_db.solutions enable row level security;

drop trigger if exists trg_set_updated_at on mock_db.solutions;
create trigger trg_set_updated_at
  before update on mock_db.solutions
  for each row execute function mock_db.set_updated_at();
