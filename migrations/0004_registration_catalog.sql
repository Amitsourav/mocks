-- ============================================================================
-- Migration 0004 — registration restructure: reference catalog + users changes
--
-- Adds config-driven reference tables for the cascading registration form
-- (State -> Mock type -> Exam name -> Country). Same RLS-enabled/no-policies
-- posture as the rest of mock_db: the backend service role serves these; the
-- anon/authenticated client roles get no direct access.
--
-- Also restructures mock_db.users for the new journey (email OTP login).
-- ============================================================================

-- ----------------------------------------------------------------------------
-- Reference tables
-- ----------------------------------------------------------------------------

-- States & Union Territories of India
create table if not exists mock_db.states (
  id         uuid primary key default gen_random_uuid(),
  code       text not null unique,          -- ISO 3166-2:IN suffix, e.g. 'MH'
  name       text not null,
  kind       text not null default 'state', -- 'state' | 'ut'
  position   integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Study-abroad destination countries (curated, extensible)
create table if not exists mock_db.countries (
  id         uuid primary key default gen_random_uuid(),
  code       text not null unique,          -- ISO 3166-1 alpha-2, e.g. 'DE'
  name       text not null,
  position   integer not null default 0,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Mock categories (the top of the cascade)
create table if not exists mock_db.mock_categories (
  id         uuid primary key default gen_random_uuid(),
  code       text not null unique,
  name       text not null,
  position   integer not null default 0,
  is_active  boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Catalog of exam names under each category (the second level of the cascade).
-- Distinct from mock_db.examinations (the actual playable mock content). A
-- catalog row MAY link to a real examination via linked_examination_id when the
-- mock exists (e.g. d-MAT); most are catalog-only selections for now.
create table if not exists mock_db.catalog_exams (
  id                    uuid primary key default gen_random_uuid(),
  category_id           uuid not null references mock_db.mock_categories(id) on delete cascade,
  code                  text not null unique,
  name                  text not null,
  position              integer not null default 0,
  requires_country      boolean not null default false,
  default_country_code  text references mock_db.countries(code) on delete set null,
  linked_examination_id uuid references mock_db.examinations(id) on delete set null,
  is_active             boolean not null default true,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now()
);

create index if not exists idx_catalog_exams_category on mock_db.catalog_exams(category_id);

-- updated_at triggers
do $$
declare
  t text;
  tables text[] := array['states','countries','mock_categories','catalog_exams'];
begin
  foreach t in array tables loop
    execute format('drop trigger if exists trg_set_updated_at on mock_db.%I;', t);
    execute format('create trigger trg_set_updated_at before update on mock_db.%I for each row execute function mock_db.set_updated_at();', t);
  end loop;
end$$;

-- RLS: enable, no policies (backend service role bypasses; clients get nothing)
do $$
declare
  t text;
  tables text[] := array['states','countries','mock_categories','catalog_exams'];
begin
  foreach t in array tables loop
    execute format('alter table mock_db.%I enable row level security;', t);
  end loop;
end$$;

-- ----------------------------------------------------------------------------
-- users table restructure
-- ----------------------------------------------------------------------------

-- Remove superseded columns (only the single test row exists).
alter table mock_db.users drop column if exists address;
alter table mock_db.users drop column if exists target_country;
alter table mock_db.users drop column if exists target_examination_id;

-- Add the new cascading-profile columns.
alter table mock_db.users
  add column if not exists state_code          text references mock_db.states(code) on delete set null,
  add column if not exists mock_category_code  text references mock_db.mock_categories(code) on delete set null,
  add column if not exists catalog_exam_code   text references mock_db.catalog_exams(code) on delete set null,
  add column if not exists target_country_code text references mock_db.countries(code) on delete set null;
