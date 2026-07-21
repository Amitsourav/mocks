-- ============================================================================
-- Migration 0011 — dMAT topic-specific skills (discriminating tags)
-- The first tagging pass left PROBLEM_SOLVING on ~72% of questions (no analytical
-- value) and Math/Latin with only ~2 distinct skill-combos. These topic skills let
-- each question be tagged by the specific technique it tests, so skill-gap analytics
-- actually discriminate. Seeded under dMAT's pool; idempotent via NOT EXISTS.
-- (Re-tagging of existing questions is applied separately by the authoring tooling.)
-- ============================================================================

insert into mock_db.skills (examination_id, code, name)
select (select id from mock_db.examinations where code = 'dMAT'), v.code, v.name
from (values
  ('MIXTURE_ALLIGATION', 'Mixtures & Alligation'),
  ('AGE_PROBLEMS', 'Age Problems'),
  ('GEOMETRY_MENSURATION', 'Geometry & Mensuration'),
  ('TIME_AND_WORK', 'Time & Work'),
  ('SPEED_DISTANCE_TIME', 'Speed, Distance & Time'),
  ('SIMPLE_INTEREST', 'Simple Interest & Investment'),
  ('NUMBER_PROPERTIES', 'Number & Digit Properties'),
  ('COST_REVENUE_MODELING', 'Cost & Revenue Modeling'),
  ('POSITIONAL_DEDUCTION', 'Positional Deduction'),
  ('DIAGONAL_CONSTRAINT', 'Diagonal Constraint')
) as v(code, name)
where not exists (select 1 from mock_db.skills s where s.code = v.code);
