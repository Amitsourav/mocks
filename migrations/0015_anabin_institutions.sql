-- ============================================================================
-- Migration 0015 — Anabin institutions (dMAT college-readiness)
--
-- The 1,307 Indian higher-ed institutions from Germany's official Anabin
-- database (anabin.kmk.org), each with its recognition status:
--   H+   = recognized (degree qualifies for a German Master's)
--   H+/- = case-by-case (recognized for some programs only)
--   H-   = not recognized
--
-- A student picks their university (users.anabin_institution_id); the
-- college-readiness endpoint combines that status with their dMAT percentile.
-- dMAT-scoped. RLS enabled/no-policies like the rest of mock_db.
-- ============================================================================

create table if not exists mock_db.anabin_institutions (
  id                uuid primary key default gen_random_uuid(),
  name              text not null,
  aliases           text[] not null default '{}',   -- name variants / abbreviations
  city              text,
  state             text,
  institution_type  text,                            -- e.g. 'State University'
  status            text not null,                   -- 'H+' | 'H+/-' | 'H-'
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists idx_anabin_status on mock_db.anabin_institutions(status);
-- Typeahead is ILIKE over name + aliases; trigram makes it fast and fuzzy.
create extension if not exists pg_trgm;
create index if not exists idx_anabin_name_trgm on mock_db.anabin_institutions using gin (name gin_trgm_ops);

alter table mock_db.anabin_institutions enable row level security;

-- The student's own university (drives the eligibility half of the prediction).
alter table mock_db.users
  add column if not exists anabin_institution_id uuid
    references mock_db.anabin_institutions(id) on delete set null;
