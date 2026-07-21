-- ============================================================================
-- Migration 0013 — dMAT linear-mock timer = real WORKING time (no break)
-- The v1 dMAT mock is a single continuous flow (no 30-min break, no per-section
-- timers). Set total_duration_seconds to the sum of the four section working
-- limits (25+25+20+90 = 160 min = 9600s) so the one overall countdown matches the
-- real solving time. (The full 3.5-hour sitting includes a break we don't run in v1.)
-- start_attempt reads this live to compute the attempt's expires_at.
-- ============================================================================

update mock_db.examinations
set total_duration_seconds = 9600
where code = 'dMAT';
