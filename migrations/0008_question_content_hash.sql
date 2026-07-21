-- ============================================================================
-- Migration 0008 — question dedup guard
-- A content_hash fingerprint on questions + a unique index, so the database
-- rejects EXACT-duplicate questions (last-line guard behind the pipeline's
-- hash + embedding dedup). Partial-unique so existing/null-hash rows are exempt.
-- ============================================================================

alter table mock_db.questions
  add column if not exists content_hash text;

-- One question per fingerprint (NULLs exempt: rows without a hash never clash).
create unique index if not exists uq_questions_content_hash
  on mock_db.questions(content_hash)
  where content_hash is not null;
