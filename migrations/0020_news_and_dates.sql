-- ============================================================================
-- Migration 0020 — auto-ingested "Dates & News" for Germany-bound students
--
-- Two tables backing the frontend "Dates & News" page. Ingestion runs in the
-- backend (app/services/news_ingest.py) on startup + every 6h, so news
-- accumulates and schedule changes are detected automatically; the frontend
-- only renders.
--
--   news_items  — accumulating feed of official updates (APS document history,
--                 detected schedule changes, and any RSS/Atom items that parse).
--                 `relevant=false` rows are kept for audit but never served.
--   exam_dates  — the canonical dMAT schedule the sidebar renders. Seeded here
--                 with the current official values; the ingester updates a row
--                 (and logs a news_item) when the official site changes a date.
--
-- RLS enabled / no client policies, like the rest of mock_db — the backend
-- service role bypasses RLS and is the only reader/writer.
-- ============================================================================

create table if not exists mock_db.news_items (
  id           uuid primary key default gen_random_uuid(),
  source       text not null,                       -- 'aps_india' | 'daad' | 'gast' | 'embassy_india'
  source_name  text not null,                       -- display name, e.g. 'APS India'
  url          text,                                -- link to the item; null for scraped prose
  title        text not null,
  summary      text,                                -- 1–2 sentence plain-text summary
  category     text not null default 'general',
  published_at timestamptz not null,
  dedup_key    text not null unique,                -- sha256(source + (url|title)) — blocks re-inserts
  relevant     boolean not null default true,       -- false = fetched but filtered out (audit only)
  created_at   timestamptz not null default now(),
  constraint news_items_category_chk
    check (category in ('aps', 'dmat', 'visa', 'exams', 'scholarships', 'deadlines', 'general'))
);

create index if not exists idx_news_items_relevant_published
  on mock_db.news_items (relevant, published_at desc);

alter table mock_db.news_items enable row level security;

create table if not exists mock_db.exam_dates (
  id         uuid primary key default gen_random_uuid(),
  label      text not null unique,   -- canonical milestone label
  date       date,                   -- null for undated milestones ("Summer 2027")
  display    text not null,          -- human form: '15 Sep 2026', 'Summer 2027'
  updated_at timestamptz not null default now()
);

alter table mock_db.exam_dates enable row level security;

-- Seed the current official schedule (source: aps-india.de/dmat, 2026 cohort).
insert into mock_db.exam_dates (label, date, display) values
  ('Registration opens',    date '2026-06-29', '29 Jun 2026'),
  ('Registration deadline', date '2026-09-15', '15 Sep 2026'),
  ('dMAT test date',        date '2026-09-26', '26 Sep 2026'),
  ('Certificate available', date '2026-10-12', '12 Oct 2026'),
  ('dMAT mandatory in APS', null,              'Summer 2027')
on conflict (label) do nothing;
