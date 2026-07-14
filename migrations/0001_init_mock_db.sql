-- ============================================================================
-- Migration 0001 — initialize mock_db schema
-- Universal mock-examination platform (backend).
-- Hierarchy: Exam -> Module -> Section -> Question. Feature-flag driven.
-- Idempotent where practical (IF NOT EXISTS / DO blocks) so it is safe to re-run.
-- ============================================================================

create schema if not exists mock_db;

-- pgcrypto provides gen_random_uuid()
create extension if not exists pgcrypto;

-- ----------------------------------------------------------------------------
-- Enums (guarded so re-running the migration does not error)
-- ----------------------------------------------------------------------------
do $$
begin
  if not exists (select 1 from pg_type t join pg_namespace n on n.oid = t.typnamespace
                 where t.typname = 'user_role' and n.nspname = 'mock_db') then
    create type mock_db.user_role as enum ('student', 'author', 'admin');
  end if;

  if not exists (select 1 from pg_type t join pg_namespace n on n.oid = t.typnamespace
                 where t.typname = 'scoring_type' and n.nspname = 'mock_db') then
    create type mock_db.scoring_type as enum ('normalised', 'raw', 'scaled', 'percentile');
  end if;

  if not exists (select 1 from pg_type t join pg_namespace n on n.oid = t.typnamespace
                 where t.typname = 'question_type' and n.nspname = 'mock_db') then
    create type mock_db.question_type as enum ('single_choice', 'multi_select', 'numeric_entry', 'essay');
  end if;

  if not exists (select 1 from pg_type t join pg_namespace n on n.oid = t.typnamespace
                 where t.typname = 'content_status' and n.nspname = 'mock_db') then
    create type mock_db.content_status as enum ('draft', 'published', 'archived');
  end if;

  if not exists (select 1 from pg_type t join pg_namespace n on n.oid = t.typnamespace
                 where t.typname = 'attempt_status' and n.nspname = 'mock_db') then
    create type mock_db.attempt_status as enum ('in_progress', 'submitted', 'expired', 'abandoned');
  end if;

  if not exists (select 1 from pg_type t join pg_namespace n on n.oid = t.typnamespace
                 where t.typname = 'section_progress' and n.nspname = 'mock_db') then
    create type mock_db.section_progress as enum ('not_started', 'in_progress', 'completed');
  end if;

  if not exists (select 1 from pg_type t join pg_namespace n on n.oid = t.typnamespace
                 where t.typname = 'event_type' and n.nspname = 'mock_db') then
    create type mock_db.event_type as enum (
      'section_entered', 'section_completed',
      'question_viewed', 'answer_submitted', 'question_revisited', 'marked_for_review',
      'focus_lost', 'focus_regained', 'fullscreen_exit', 'fullscreen_enter'
    );
  end if;
end$$;

-- ----------------------------------------------------------------------------
-- updated_at trigger helper
-- ----------------------------------------------------------------------------
create or replace function mock_db.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ============================================================================
-- B. Exam structure (created before A/users because users.target_examination_id
--    references examinations)
-- ============================================================================

create table if not exists mock_db.examinations (
  id                              uuid primary key default gen_random_uuid(),
  code                            text not null unique,
  name                            text not null,
  description                     text,
  is_active                       boolean not null default false,
  language                        text not null default 'en',
  total_duration_seconds          integer,
  -- capability flags (the per-exam switchboard)
  has_single_choice               boolean not null default true,
  has_multi_select                boolean not null default false,
  has_numeric_entry               boolean not null default false,
  has_essay                       boolean not null default false,
  has_negative_marking            boolean not null default false,
  penalizes_unanswered            boolean not null default false,
  has_sectional_time_limits       boolean not null default true,
  section_navigation_locked       boolean not null default true,
  allows_revisit_within_section   boolean not null default true,
  has_shared_stimulus             boolean not null default false,
  has_images                      boolean not null default false,
  has_math                        boolean not null default false,
  default_time_per_question_seconds integer,
  scoring_type                    mock_db.scoring_type not null default 'raw',
  scoring_config                  jsonb not null default '{}'::jsonb,
  created_at                      timestamptz not null default now(),
  updated_at                      timestamptz not null default now()
);

create table if not exists mock_db.exam_modules (
  id                uuid primary key default gen_random_uuid(),
  examination_id    uuid not null references mock_db.examinations(id) on delete cascade,
  code              text not null,
  name              text not null,
  position          integer not null default 0,
  duration_seconds  integer,
  has_break_after   boolean not null default false,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (examination_id, code)
);

create table if not exists mock_db.exam_sections (
  id                 uuid primary key default gen_random_uuid(),
  module_id          uuid not null references mock_db.exam_modules(id) on delete cascade,
  examination_id     uuid not null references mock_db.examinations(id) on delete cascade,
  code               text not null,
  name               text not null,
  position           integer not null default 0,
  time_limit_seconds integer,
  question_count     integer,
  navigation_locked  boolean not null default true,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  unique (module_id, code)
);

create table if not exists mock_db.subjects (
  id             uuid primary key default gen_random_uuid(),
  examination_id uuid not null references mock_db.examinations(id) on delete cascade,
  code           text not null,
  name           text not null,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  unique (examination_id, code)
);

-- ============================================================================
-- A. Identity & profile (1:1 with Supabase auth.users)
-- ============================================================================

create table if not exists mock_db.users (
  id                     uuid primary key default gen_random_uuid(),
  auth_user_id           uuid not null unique references auth.users(id) on delete cascade,
  full_name              text,
  email                  text,
  phone                  text,
  address                text,
  target_country         text,
  target_examination_id  uuid references mock_db.examinations(id) on delete set null,
  role                   mock_db.user_role not null default 'student',
  profile_completed      boolean not null default false,
  created_at             timestamptz not null default now(),
  updated_at             timestamptz not null default now()
);

create index if not exists idx_users_auth_user_id on mock_db.users(auth_user_id);
create index if not exists idx_users_role on mock_db.users(role);

-- ============================================================================
-- C. Questions & content
-- ============================================================================

create table if not exists mock_db.media_assets (
  id           uuid primary key default gen_random_uuid(),
  bucket       text not null default 'exam-media',
  storage_path text not null,
  kind         text not null default 'image',
  alt_text     text,
  width        integer,
  height       integer,
  uploaded_by  uuid references mock_db.users(id) on delete set null,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  unique (bucket, storage_path)
);

create table if not exists mock_db.stimuli (
  id             uuid primary key default gen_random_uuid(),
  examination_id uuid not null references mock_db.examinations(id) on delete cascade,
  section_id     uuid references mock_db.exam_sections(id) on delete set null,
  content_md     text not null,
  status         mock_db.content_status not null default 'draft',
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create table if not exists mock_db.questions (
  id                 uuid primary key default gen_random_uuid(),
  examination_id     uuid not null references mock_db.examinations(id) on delete cascade,
  section_id         uuid not null references mock_db.exam_sections(id) on delete cascade,
  subject_id         uuid references mock_db.subjects(id) on delete set null,
  stimulus_id        uuid references mock_db.stimuli(id) on delete set null,
  question_type      mock_db.question_type not null default 'single_choice',
  content_md         text not null,
  position           integer not null default 0,
  difficulty         smallint,
  marks              numeric(6,2) not null default 1,
  negative_marks     numeric(6,2) not null default 0,
  numeric_answer_key text,                          -- for numeric_entry (TITA)
  explanation_md     text,                          -- for later analysis
  status             mock_db.content_status not null default 'draft',
  version            integer not null default 1,
  created_by         uuid references mock_db.users(id) on delete set null,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create index if not exists idx_questions_section_status_pos
  on mock_db.questions(section_id, status, position);
create index if not exists idx_questions_examination on mock_db.questions(examination_id);
create index if not exists idx_questions_stimulus on mock_db.questions(stimulus_id);

create table if not exists mock_db.question_options (
  id          uuid primary key default gen_random_uuid(),
  question_id uuid not null references mock_db.questions(id) on delete cascade,
  label       text,                                 -- 'A','B','C','D'
  content_md  text not null,
  is_correct  boolean not null default false,       -- SECRET: never sent to client mid-test
  position    integer not null default 0,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists idx_question_options_question on mock_db.question_options(question_id);

-- ============================================================================
-- D. Skills & tagging (normalized)
-- ============================================================================

create table if not exists mock_db.skills (
  id             uuid primary key default gen_random_uuid(),
  examination_id uuid references mock_db.examinations(id) on delete cascade,  -- null = global
  code           text not null,
  name           text not null,
  description    text,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

-- unique code per exam (and per global scope)
create unique index if not exists uq_skills_exam_code
  on mock_db.skills(coalesce(examination_id, '00000000-0000-0000-0000-000000000000'::uuid), code);

create table if not exists mock_db.question_skill_tags (
  question_id uuid not null references mock_db.questions(id) on delete cascade,
  skill_id    uuid not null references mock_db.skills(id) on delete cascade,
  created_at  timestamptz not null default now(),
  primary key (question_id, skill_id)
);

create index if not exists idx_qst_skill on mock_db.question_skill_tags(skill_id);

-- ============================================================================
-- E. Attempts, responses & event log (raw capture)
-- ============================================================================

create table if not exists mock_db.attempts (
  id                 uuid primary key default gen_random_uuid(),
  user_id            uuid not null references mock_db.users(id) on delete cascade,
  examination_id     uuid not null references mock_db.examinations(id) on delete cascade,
  status             mock_db.attempt_status not null default 'in_progress',
  started_at         timestamptz,
  submitted_at       timestamptz,
  expires_at         timestamptz,
  current_module_id  uuid references mock_db.exam_modules(id) on delete set null,
  current_section_id uuid references mock_db.exam_sections(id) on delete set null,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create index if not exists idx_attempts_user_status on mock_db.attempts(user_id, status);
create index if not exists idx_attempts_examination on mock_db.attempts(examination_id);
-- one active (in_progress) attempt per user per exam
create unique index if not exists uq_attempts_one_active
  on mock_db.attempts(user_id, examination_id)
  where status = 'in_progress';

create table if not exists mock_db.attempt_sections (
  id           uuid primary key default gen_random_uuid(),
  attempt_id   uuid not null references mock_db.attempts(id) on delete cascade,
  section_id   uuid not null references mock_db.exam_sections(id) on delete cascade,
  status       mock_db.section_progress not null default 'not_started',
  started_at   timestamptz,
  deadline_at  timestamptz,                          -- server-authoritative
  submitted_at timestamptz,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  unique (attempt_id, section_id)
);

create index if not exists idx_attempt_sections_attempt on mock_db.attempt_sections(attempt_id);

create table if not exists mock_db.student_answers (
  id                  uuid primary key default gen_random_uuid(),
  attempt_id          uuid not null references mock_db.attempts(id) on delete cascade,
  question_id         uuid not null references mock_db.questions(id) on delete cascade,
  user_id             uuid not null references mock_db.users(id) on delete cascade,
  selected_option_id  uuid references mock_db.question_options(id) on delete set null,
  selected_option_ids uuid[],                         -- multi_select
  numeric_answer      text,                           -- numeric_entry
  text_answer         text,                           -- essay
  is_marked_for_review boolean not null default false,
  is_correct          boolean,                        -- filled by later scoring pipeline
  time_spent_ms       integer,                        -- derived later from events
  answered_at         timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (attempt_id, question_id)
);

create index if not exists idx_student_answers_attempt on mock_db.student_answers(attempt_id);
create index if not exists idx_student_answers_question on mock_db.student_answers(question_id);

create table if not exists mock_db.question_events (
  id                 uuid primary key default gen_random_uuid(),
  attempt_id         uuid not null references mock_db.attempts(id) on delete cascade,
  section_id         uuid references mock_db.exam_sections(id) on delete set null,
  question_id        uuid references mock_db.questions(id) on delete set null,
  event_type         mock_db.event_type not null,
  occurred_at        timestamptz not null default now(),  -- server timestamp
  client_occurred_at timestamptz,                          -- optional client timestamp
  metadata           jsonb not null default '{}'::jsonb,
  created_at         timestamptz not null default now()
);

create index if not exists idx_question_events_attempt_time
  on mock_db.question_events(attempt_id, occurred_at);
create index if not exists idx_question_events_question on mock_db.question_events(question_id);

-- ============================================================================
-- updated_at triggers for all mutable tables
-- ============================================================================
do $$
declare
  t text;
  tables text[] := array[
    'examinations','exam_modules','exam_sections','subjects','users',
    'media_assets','stimuli','questions','question_options','skills',
    'attempts','attempt_sections','student_answers'
  ];
begin
  foreach t in array tables loop
    execute format('drop trigger if exists trg_set_updated_at on mock_db.%I;', t);
    execute format(
      'create trigger trg_set_updated_at before update on mock_db.%I
       for each row execute function mock_db.set_updated_at();', t);
  end loop;
end$$;
