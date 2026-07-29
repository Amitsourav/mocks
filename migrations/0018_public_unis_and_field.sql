-- ============================================================================
-- Migration 0018 — public/private flag on DAAD programmes + student's dMAT field
--
-- The college predictor shows German PUBLIC universities in the student's field.
-- Two additions:
--   1. daad_programs.is_public — whether the institution is state-run (public,
--      tuition-free) vs private. Classified against the HRK Hochschulkompass
--      registry (see scripts/seed_public_flag.py). Nullable until classified.
--   2. users.dmat_field — the student's UG field, one of the three dMAT notified
--      fields (Engineering; Commerce/Finance/Economics; Business/Management).
--      Used to auto-scope the programme list. Values validated in the API layer.
-- ============================================================================

alter table mock_db.daad_programs
  add column if not exists is_public boolean;

alter table mock_db.users
  add column if not exists dmat_field text;

-- Partial index: the programme list always filters to public institutions.
create index if not exists idx_daad_programs_public
  on mock_db.daad_programs (university) where is_public is true;
