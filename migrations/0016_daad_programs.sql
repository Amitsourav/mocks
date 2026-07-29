-- ============================================================================
-- Migration 0016 — DAAD Master's programmes (target-university list)
--
-- 1,716 English/international Master's programmes at German universities, from
-- the official DAAD "International Programmes" database (daad.de). Powers the
-- honest "programmes you can target" list: real German public universities in
-- the student's field, overlaid with their Anabin eligibility + grade tier.
--
-- NOTE: DAAD publishes no per-programme grade cut-off (German admission is
-- holistic), so this table intentionally has no cutoff column — fit is shown at
-- the grade-TIER level, not as a fake per-programme guarantee. dMAT-scoped.
-- ============================================================================

create table if not exists mock_db.daad_programs (
  id                   uuid primary key default gen_random_uuid(),
  daad_id              text unique,
  name                 text not null,
  university           text not null,
  city                 text,
  languages            text[] not null default '{}',
  subject              text,
  tuition              text,
  duration             text,
  application_deadline text,
  link                 text,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

create index if not exists idx_daad_subject on mock_db.daad_programs(subject);
-- Field search is ILIKE over name + subject; trigram keeps it fast/fuzzy.
create index if not exists idx_daad_name_trgm on mock_db.daad_programs using gin (name gin_trgm_ops);
create index if not exists idx_daad_subject_trgm on mock_db.daad_programs using gin (subject gin_trgm_ops);

alter table mock_db.daad_programs enable row level security;
