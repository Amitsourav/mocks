-- ============================================================================
-- Migration 0017 — academic inputs for the dMAT college-readiness formula
--
-- The readiness score combines: UG grade (Modified Bavarian Formula) + dMAT
-- percentile + 12th% + the Anabin eligibility gate. These two columns capture
-- the academic inputs the student provides. (course/field is already the
-- student's catalog_exam/stream; DAAD field filtering is passed per-request.)
-- ============================================================================

alter table mock_db.users
  add column if not exists ug_percentage      numeric(5,2),   -- undergraduate %
  add column if not exists twelfth_percentage numeric(5,2);   -- class XII %
