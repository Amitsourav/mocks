-- ============================================================================
-- Migration 0019 — per-programme admission mode (zulassungsfrei / -beschränkt)
--
-- Each German Master's programme is officially either open admission
-- (zulassungsfrei) or restricted/selective (zulassungsbeschränkt, incl. any
-- NC / Eignungsfeststellungsverfahren). The DAAD International Programmes feed
-- does NOT carry this flag; the authoritative source is the HRK Hochschulkompass
-- (field "Zulassungsmodus"), ingested separately. Nullable + honest: null means
-- "unknown for that programme", never a guess.
--
--   'open'       = zulassungsfrei
--   'restricted' = zulassungsbeschränkt (any NC / selection procedure)
--   null         = unknown
-- ============================================================================

alter table mock_db.daad_programs
  add column if not exists admission_mode text;

alter table mock_db.daad_programs
  drop constraint if exists daad_programs_admission_mode_chk;
alter table mock_db.daad_programs
  add constraint daad_programs_admission_mode_chk
  check (admission_mode in ('open', 'restricted'));
