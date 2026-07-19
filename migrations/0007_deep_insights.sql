-- ============================================================================
-- Migration 0007 — Round 5: deep AI insight layer
-- Concept layer (below skills), per-concept mastery with decay, error-typing on
-- question results, and qualitative insight stores (per-attempt + evolving
-- student profile). Sample is crafted now; the same schema is filled by the
-- OpenRouter AI pipeline on real data later.
-- Same posture: uuid PKs, updated_at triggers, RLS enabled no-policies.
-- ============================================================================

-- enums
do $$
begin
  if not exists (select 1 from pg_type t join pg_namespace n on n.oid=t.typnamespace
                 where t.typname='kc_type' and n.nspname='mock_db') then
    create type mock_db.kc_type as enum ('fact','procedure','concept');
  end if;
  if not exists (select 1 from pg_type t join pg_namespace n on n.oid=t.typnamespace
                 where t.typname='kc_source' and n.nspname='mock_db') then
    create type mock_db.kc_source as enum ('seed','ai_derived');
  end if;
  if not exists (select 1 from pg_type t join pg_namespace n on n.oid=t.typnamespace
                 where t.typname='error_type' and n.nspname='mock_db') then
    create type mock_db.error_type as enum
      ('correct','careless','conceptual','procedural','guess','unattempted');
  end if;
  if not exists (select 1 from pg_type t join pg_namespace n on n.oid=t.typnamespace
                 where t.typname='insight_source' and n.nspname='mock_db') then
    create type mock_db.insight_source as enum ('crafted','ai');
  end if;
end$$;

-- ---- Concept layer (below skills) ----
create table if not exists mock_db.knowledge_components (
  id                uuid primary key default gen_random_uuid(),
  subject_id        uuid references mock_db.syllabus_subjects(id) on delete cascade,
  catalog_exam_code text,
  code              text not null unique,
  name              text not null,
  description       text,
  kc_type           mock_db.kc_type not null default 'concept',
  source            mock_db.kc_source not null default 'seed',
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);
create index if not exists idx_kc_subject on mock_db.knowledge_components(subject_id);
create index if not exists idx_kc_exam on mock_db.knowledge_components(catalog_exam_code);

-- ---- Per-(student, concept) mastery with decay ----
create table if not exists mock_db.student_concept_mastery (
  id                     uuid primary key default gen_random_uuid(),
  user_id                uuid not null references mock_db.users(id) on delete cascade,
  kc_id                  uuid not null references mock_db.knowledge_components(id) on delete cascade,
  p_mastery              numeric(4,3) not null default 0,     -- 0..1 (BKT posterior)
  n_opportunities        integer not null default 0,
  retention_probability  numeric(4,3),                        -- mastery decayed by time
  last_correct_at        timestamptz,
  next_review_due        timestamptz,
  careless_rate          numeric(4,3),
  conceptual_gap_score   numeric(4,3),
  avg_time_z             numeric(6,3),                        -- response-time z vs cohort
  dominant_misconception text,
  gap_priority           numeric(6,3),                        -- (1-retention)*weight*recency
  is_dummy               boolean not null default false,
  updated_at             timestamptz not null default now(),
  unique (user_id, kc_id)
);
create index if not exists idx_scm_user_priority on mock_db.student_concept_mastery(user_id, gap_priority desc);

-- ---- Error-typing + concept link on question results ----
alter table mock_db.attempt_question_results
  add column if not exists kc_code text,
  add column if not exists error_type mock_db.error_type,
  add column if not exists misconception_note text,
  add column if not exists student_confidence text;   -- for calibration (self-rated)
create index if not exists idx_aqr_error_type on mock_db.attempt_question_results(error_type);

-- ---- Per-attempt qualitative + behavioral insight ----
create table if not exists mock_db.attempt_insights (
  id                   uuid primary key default gen_random_uuid(),
  attempt_result_id    uuid not null unique references mock_db.attempt_results(id) on delete cascade,
  headline             text,
  goal                 text,          -- feed-up: where you're going
  current_status       text,          -- feed-back: where you are (process level)
  gap_diagnosis        text,          -- why the gap exists
  calibration_note     text,          -- confidence vs performance
  next_actions         jsonb not null default '[]'::jsonb,   -- ordered, 1-3 concrete actions
  recommended_method   text,          -- retrieval + spacing
  behavior_archetype   text,          -- e.g. 'Jumping Around', 'Marathoner'
  pacing_note          text,
  negative_marking_loss numeric(8,2),
  guess_rate           numeric(5,2),
  calibration_gap      numeric(5,2),
  generated_by         mock_db.insight_source not null default 'crafted',
  model                text,
  is_dummy             boolean not null default false,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

-- ---- Evolving student profile (latest by created_at = current) ----
create table if not exists mock_db.student_insights (
  id                        uuid primary key default gen_random_uuid(),
  user_id                   uuid not null references mock_db.users(id) on delete cascade,
  stream_catalog_exam_code  text,
  summary                   text,
  persistent_strengths      jsonb not null default '[]'::jsonb,
  persistent_gaps           jsonb not null default '[]'::jsonb,
  predicted_score           numeric(8,2),
  predicted_band_low        numeric(8,2),
  predicted_band_high       numeric(8,2),
  study_plan                jsonb not null default '[]'::jsonb,   -- ordered steps
  generated_by              mock_db.insight_source not null default 'crafted',
  model                     text,
  is_dummy                  boolean not null default false,
  created_at                timestamptz not null default now()
);
create index if not exists idx_student_insights_latest on mock_db.student_insights(user_id, created_at desc);

-- ---- updated_at triggers ----
do $$
declare t text; tables text[] := array['knowledge_components','student_concept_mastery','attempt_insights'];
begin
  foreach t in array tables loop
    execute format('drop trigger if exists trg_set_updated_at on mock_db.%I;', t);
    execute format('create trigger trg_set_updated_at before update on mock_db.%I for each row execute function mock_db.set_updated_at();', t);
  end loop;
end$$;

-- ---- RLS: enable, no policies ----
do $$
declare t text; tables text[] := array['knowledge_components','student_concept_mastery','attempt_insights','student_insights'];
begin
  foreach t in array tables loop
    execute format('alter table mock_db.%I enable row level security;', t);
  end loop;
end$$;
