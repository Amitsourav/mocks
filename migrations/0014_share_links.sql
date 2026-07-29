-- ============================================================================
-- Migration 0014 — share links + leaderboard index
--
-- share_links: public, read-only report snapshots. The payload is FROZEN at
-- share time (a jsonb snapshot), so the public read-by-token endpoint never
-- touches live user data — a shared result stays "my result that day". RLS
-- enabled/no-policies like the rest of mock_db; the backend service role serves
-- it (the public endpoint is unauthenticated at the API layer, not via Supabase).
-- ============================================================================

create table if not exists mock_db.share_links (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references mock_db.users(id) on delete cascade,
  scope       text not null check (scope in ('dashboard', 'attempt')),
  -- set only for scope='attempt'; the shared attempt-detail snapshot
  attempt_id  uuid references mock_db.attempt_results(id) on delete cascade,
  token       text not null unique,          -- secrets.token_urlsafe(16), never sequential
  payload     jsonb not null,                -- the frozen report the public endpoint serves
  created_at  timestamptz not null default now(),
  expires_at  timestamptz,                   -- ~30 days out; null = never
  revoked_at  timestamptz
);

create index if not exists idx_share_links_user on mock_db.share_links(user_id);

alter table mock_db.share_links enable row level security;

-- Leaderboard: rank users by best score within a stream (catalog_exam_code).
-- The board filters attempt_results by catalog_exam_code and orders by score.
create index if not exists idx_attempt_results_stream_rank
  on mock_db.attempt_results(catalog_exam_code, score desc);
