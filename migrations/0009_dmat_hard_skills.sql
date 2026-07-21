-- ============================================================================
-- Migration 0009 — dMAT hard-skill seed
-- Adds hard/technique skills (e.g. Linear Systems, Rotation Rule) as ordinary
-- rows in mock_db.skills under dMAT's pool. Questions are tagged with these via
-- question_skill_tags alongside the 6 existing soft skills — NO skill_type column,
-- NO schema/UI change. skills.code has no unique constraint, so idempotency is via
-- NOT EXISTS (safe to re-run; skips any code that already exists anywhere).
-- ============================================================================

insert into mock_db.skills (examination_id, code, name)
select (select id from mock_db.examinations where code = 'dMAT'), v.code, v.name
from (values
  ('ROTATION_RULE', 'Rotation Rule'),
  ('REFLECTION_RULE', 'Reflection/Mirror Rule'),
  ('TRANSLATION_RULE', 'Translation/Movement Rule'),
  ('PROGRESSION_COUNTING', 'Progression & Counting'),
  ('SHAPE_TRANSFORMATION', 'Shape Transformation'),
  ('FILL_SHADING_RULE', 'Fill/Shading Rule'),
  ('LINEAR_SYSTEMS', 'Linear Systems of Equations'),
  ('SUBSTITUTION_METHOD', 'Substitution Method'),
  ('ELIMINATION_METHOD', 'Elimination Method'),
  ('WORD_PROBLEM_MODELING', 'Word-Problem to Equation Modeling'),
  ('RATIO_PROPORTION', 'Ratio & Proportion'),
  ('CONSTRAINT_ELIMINATION', 'Constraint Elimination'),
  ('ROW_COLUMN_DEDUCTION', 'Row/Column Deduction'),
  ('UNIQUENESS_REASONING', 'Uniqueness Reasoning'),
  ('MAIN_IDEA', 'Main Idea & Purpose'),
  ('INFERENCE', 'Inference'),
  ('DETAIL_RETRIEVAL', 'Detail Retrieval'),
  ('DATA_INTERPRETATION', 'Data Interpretation'),
  ('CRITICAL_REASONING', 'Critical Reasoning'),
  ('VOCABULARY_IN_CONTEXT', 'Vocabulary in Context')
) as v(code, name)
where not exists (select 1 from mock_db.skills s where s.code = v.code);
