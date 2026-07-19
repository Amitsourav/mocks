-- ============================================================================
-- Migration 0006 — Round 4 schema: syllabus catalog, mock tests, exam-stream
-- history (append-only), and analytics tables (dummy now, real-shaped).
--
-- Same posture as the rest of mock_db: uuid PKs, updated_at triggers, RLS
-- enabled with no policies (backend service role serves; clients get nothing).
-- ============================================================================

-- enum for mock test scope
do $$
begin
  if not exists (select 1 from pg_type t join pg_namespace n on n.oid=t.typnamespace
                 where t.typname='mock_scope' and n.nspname='mock_db') then
    create type mock_db.mock_scope as enum ('full', 'subject', 'chapter');
  end if;
  if not exists (select 1 from pg_type t join pg_namespace n on n.oid=t.typnamespace
                 where t.typname='stream_source' and n.nspname='mock_db') then
    create type mock_db.stream_source as enum ('registration', 'switch');
  end if;
end$$;

-- ----------------------------------------------------------------------------
-- Reference/catalog (REAL data)
-- ----------------------------------------------------------------------------

-- Optional sub-exams under a catalog_exams family (mainly govt: Bank -> IBPS PO)
create table if not exists mock_db.exam_variants (
  id              uuid primary key default gen_random_uuid(),
  catalog_exam_id uuid not null references mock_db.catalog_exams(id) on delete cascade,
  code            text not null unique,
  name            text not null,
  position        integer not null default 0,
  is_active       boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index if not exists idx_exam_variants_exam on mock_db.exam_variants(catalog_exam_id);

-- A subject/section. Owned by EITHER a category (shared sectionals like govt
-- "English") OR a specific catalog exam. Exactly one owner.
create table if not exists mock_db.syllabus_subjects (
  id              uuid primary key default gen_random_uuid(),
  category_id     uuid references mock_db.mock_categories(id) on delete cascade,
  catalog_exam_id uuid references mock_db.catalog_exams(id) on delete cascade,
  code            text not null unique,
  name            text not null,
  position        integer not null default 0,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  constraint syllabus_subjects_one_owner
    check ( (category_id is not null)::int + (catalog_exam_id is not null)::int = 1 )
);
create index if not exists idx_syllabus_subjects_category on mock_db.syllabus_subjects(category_id);
create index if not exists idx_syllabus_subjects_exam on mock_db.syllabus_subjects(catalog_exam_id);

-- Chapters / topics within a subject (CBSE chapters; competitive topics)
create table if not exists mock_db.syllabus_chapters (
  id         uuid primary key default gen_random_uuid(),
  subject_id uuid not null references mock_db.syllabus_subjects(id) on delete cascade,
  code       text not null unique,
  name       text not null,
  position   integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists idx_syllabus_chapters_subject on mock_db.syllabus_chapters(subject_id);

-- Browsable mock tests (full / subject / chapter scope)
create table if not exists mock_db.mock_tests (
  id                    uuid primary key default gen_random_uuid(),
  scope                 mock_db.mock_scope not null,
  category_id           uuid references mock_db.mock_categories(id) on delete cascade,
  catalog_exam_id       uuid references mock_db.catalog_exams(id) on delete cascade,
  variant_id            uuid references mock_db.exam_variants(id) on delete set null,
  subject_id            uuid references mock_db.syllabus_subjects(id) on delete set null,
  chapter_id            uuid references mock_db.syllabus_chapters(id) on delete set null,
  title                 text not null,
  description           text,
  duration_seconds      integer,
  total_questions       integer,
  difficulty            text,
  position              integer not null default 0,
  linked_examination_id uuid references mock_db.examinations(id) on delete set null,
  is_active             boolean not null default true,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);
create index if not exists idx_mock_tests_exam on mock_db.mock_tests(catalog_exam_id);
create index if not exists idx_mock_tests_category on mock_db.mock_tests(category_id);
create index if not exists idx_mock_tests_subject on mock_db.mock_tests(subject_id);
create index if not exists idx_mock_tests_scope on mock_db.mock_tests(scope);

-- Extend skills to attach to the broad catalog (keep examination_id for engine)
alter table mock_db.skills
  add column if not exists catalog_exam_id uuid references mock_db.catalog_exams(id) on delete cascade,
  add column if not exists subject_id uuid references mock_db.syllabus_subjects(id) on delete set null;
create index if not exists idx_skills_catalog_exam on mock_db.skills(catalog_exam_id);

-- ----------------------------------------------------------------------------
-- Profile: append-only exam-stream history
-- ----------------------------------------------------------------------------
create table if not exists mock_db.user_stream_selections (
  id                  uuid primary key default gen_random_uuid(),
  user_id             uuid not null references mock_db.users(id) on delete cascade,
  category_code       text not null references mock_db.mock_categories(code),
  catalog_exam_code   text not null references mock_db.catalog_exams(code),
  variant_code        text references mock_db.exam_variants(code),
  target_country_code text references mock_db.countries(code),
  source              mock_db.stream_source not null default 'switch',
  created_at          timestamptz not null default now()
);
-- current stream = latest row per user by created_at
create index if not exists idx_user_stream_latest on mock_db.user_stream_selections(user_id, created_at desc);

-- ----------------------------------------------------------------------------
-- Analytics (DUMMY now, real-shaped — the deferred D7 output schema)
-- ----------------------------------------------------------------------------
create table if not exists mock_db.attempt_results (
  id                uuid primary key default gen_random_uuid(),
  user_id           uuid not null references mock_db.users(id) on delete cascade,
  mock_test_id      uuid references mock_db.mock_tests(id) on delete set null,
  catalog_exam_code text,
  engine_attempt_id uuid references mock_db.attempts(id) on delete set null,
  started_at        timestamptz,
  submitted_at      timestamptz,
  duration_seconds  integer,
  total_questions   integer,
  attempted         integer,
  correct           integer,
  wrong             integer,
  skipped           integer,
  score             numeric(8,2),
  max_score         numeric(8,2),
  percentile        numeric(5,2),
  accuracy_pct      numeric(5,2),
  is_dummy          boolean not null default false,
  created_at        timestamptz not null default now()
);
create index if not exists idx_attempt_results_user on mock_db.attempt_results(user_id, submitted_at desc);

create table if not exists mock_db.attempt_section_results (
  id                uuid primary key default gen_random_uuid(),
  attempt_result_id uuid not null references mock_db.attempt_results(id) on delete cascade,
  section_name      text not null,
  total             integer,
  correct           integer,
  wrong             integer,
  skipped           integer,
  score             numeric(8,2),
  accuracy_pct      numeric(5,2),
  avg_time_ms       integer,
  position          integer not null default 0
);
create index if not exists idx_attempt_section_results_ar on mock_db.attempt_section_results(attempt_result_id);

create table if not exists mock_db.attempt_skill_results (
  id                uuid primary key default gen_random_uuid(),
  attempt_result_id uuid not null references mock_db.attempt_results(id) on delete cascade,
  skill_code        text,
  skill_name        text not null,
  total             integer,
  correct           integer,
  accuracy_pct      numeric(5,2),
  avg_time_ms       integer
);
create index if not exists idx_attempt_skill_results_ar on mock_db.attempt_skill_results(attempt_result_id);

create table if not exists mock_db.attempt_question_results (
  id                uuid primary key default gen_random_uuid(),
  attempt_result_id uuid not null references mock_db.attempt_results(id) on delete cascade,
  question_no       integer not null,
  section_name      text,
  skill_code        text,
  is_correct        boolean,
  time_spent_ms     integer,
  difficulty        text,
  marked_for_review boolean not null default false
);
create index if not exists idx_attempt_question_results_ar on mock_db.attempt_question_results(attempt_result_id);

-- ----------------------------------------------------------------------------
-- updated_at triggers (mutable tables only)
-- ----------------------------------------------------------------------------
do $$
declare
  t text;
  tables text[] := array[
    'exam_variants','syllabus_subjects','syllabus_chapters','mock_tests'
  ];
begin
  foreach t in array tables loop
    execute format('drop trigger if exists trg_set_updated_at on mock_db.%I;', t);
    execute format('create trigger trg_set_updated_at before update on mock_db.%I for each row execute function mock_db.set_updated_at();', t);
  end loop;
end$$;

-- ----------------------------------------------------------------------------
-- RLS: enable, no policies (backend service role bypasses)
-- ----------------------------------------------------------------------------
do $$
declare
  t text;
  tables text[] := array[
    'exam_variants','syllabus_subjects','syllabus_chapters','mock_tests',
    'user_stream_selections','attempt_results','attempt_section_results',
    'attempt_skill_results','attempt_question_results'
  ];
begin
  foreach t in array tables loop
    execute format('alter table mock_db.%I enable row level security;', t);
  end loop;
end$$;

-- ----------------------------------------------------------------------------
-- Backfill: seed a 'registration' stream row for existing completed profiles so
-- the append-only log has their initial choice.
-- ----------------------------------------------------------------------------
insert into mock_db.user_stream_selections
  (user_id, category_code, catalog_exam_code, target_country_code, source, created_at)
select u.id, u.mock_category_code, u.catalog_exam_code, u.target_country_code, 'registration', coalesce(u.updated_at, now())
from mock_db.users u
where u.profile_completed = true
  and u.mock_category_code is not null
  and u.catalog_exam_code is not null
  and not exists (select 1 from mock_db.user_stream_selections s where s.user_id = u.id);
