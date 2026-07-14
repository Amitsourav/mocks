-- ============================================================================
-- Migration 0003 — seed dMAT exam structure
-- Digital Master Test (APS India / g.a.s.t.). Structure per research:
--   Core Module   -> Figure Sequences (25m), Mathematical Equations (25m),
--                    Latin Squares (20m)   [break after Core]
--   Subject Module-> General Academic (shared stimulus)
-- Single-choice, 4 options, no negative marking, blank penalty, sectional
-- time limits, section navigation locked, normalised 0-200 speed+accuracy score.
-- Idempotent via ON CONFLICT on natural keys (code).
-- ============================================================================

-- Examination + capability flags
insert into mock_db.examinations (
  code, name, description, is_active, language, total_duration_seconds,
  has_single_choice, has_multi_select, has_numeric_entry, has_essay,
  has_negative_marking, penalizes_unanswered, has_sectional_time_limits,
  section_navigation_locked, allows_revisit_within_section, has_shared_stimulus,
  has_images, has_math, default_time_per_question_seconds,
  scoring_type, scoring_config
) values (
  'dMAT',
  'Digital Master Test',
  'APS India / g.a.s.t. aptitude test for Indian graduates applying to Master''s programs in Germany.',
  true, 'en', 12600,
  true, false, false, false,
  false, true, true,
  true, true, true,
  true, true, 75,
  'normalised',
  '{"scale_min": 0, "scale_max": 200, "speed_weighted": true, "blank_penalty": true}'::jsonb
)
on conflict (code) do update set
  name = excluded.name,
  description = excluded.description,
  is_active = excluded.is_active,
  total_duration_seconds = excluded.total_duration_seconds,
  penalizes_unanswered = excluded.penalizes_unanswered,
  has_sectional_time_limits = excluded.has_sectional_time_limits,
  section_navigation_locked = excluded.section_navigation_locked,
  allows_revisit_within_section = excluded.allows_revisit_within_section,
  has_shared_stimulus = excluded.has_shared_stimulus,
  has_images = excluded.has_images,
  has_math = excluded.has_math,
  default_time_per_question_seconds = excluded.default_time_per_question_seconds,
  scoring_type = excluded.scoring_type,
  scoring_config = excluded.scoring_config;

-- Modules
with exam as (select id from mock_db.examinations where code = 'dMAT')
insert into mock_db.exam_modules (examination_id, code, name, position, duration_seconds, has_break_after)
select exam.id, m.code, m.name, m.position, m.duration_seconds, m.has_break_after
from exam,
  (values
    ('CORE',    'Core Module',    1, 4200, true),
    ('SUBJECT', 'Subject Module', 2, 5400, false)
  ) as m(code, name, position, duration_seconds, has_break_after)
on conflict (examination_id, code) do update set
  name = excluded.name, position = excluded.position,
  duration_seconds = excluded.duration_seconds, has_break_after = excluded.has_break_after;

-- Sections (subtests). Core -> 3 subtests; Subject -> General Academic.
with exam as (select id from mock_db.examinations where code = 'dMAT')
insert into mock_db.exam_sections
  (module_id, examination_id, code, name, position, time_limit_seconds, question_count, navigation_locked)
select mod.id, exam.id, s.code, s.name, s.position, s.time_limit_seconds, s.question_count, true
from exam
join mock_db.exam_modules mod on mod.examination_id = exam.id
join (values
    ('CORE',    'FIGSEQ',  'Figure Sequences',       1, 1500, 20),
    ('CORE',    'MATHEQ',  'Mathematical Equations', 2, 1500, 20),
    ('CORE',    'LATSQ',   'Latin Squares',          3, 1200, 16),
    ('SUBJECT', 'GENACAD', 'General Academic Module',1, 5400, 20)
  ) as s(module_code, code, name, position, time_limit_seconds, question_count)
  on s.module_code = mod.code
on conflict (module_id, code) do update set
  name = excluded.name, position = excluded.position,
  time_limit_seconds = excluded.time_limit_seconds, question_count = excluded.question_count;

-- Skills (exam-scoped) for the skill-gap analysis
with exam as (select id from mock_db.examinations where code = 'dMAT')
insert into mock_db.skills (examination_id, code, name, description)
select exam.id, sk.code, sk.name, sk.description
from exam,
  (values
    ('PATTERN_RECOGNITION', 'Pattern Recognition',     'Abstract visual pattern and sequence reasoning (Figure Sequences).'),
    ('SPATIAL_REASONING',   'Spatial Reasoning',       'Movement, rotation, orientation transformations.'),
    ('NUMERICAL_REASONING', 'Numerical Reasoning',     'Algebraic and arithmetic problem solving (Equations).'),
    ('LOGICAL_DEDUCTION',   'Logical Deduction',       'Rule-based constraint solving (Latin Squares).'),
    ('PROBLEM_SOLVING',     'Problem Solving',         'General applied problem solving.'),
    ('READING_COMPREHENSION','Reading Comprehension',  'Understanding and applying a short problem statement (General Academic).')
  ) as sk(code, name, description)
on conflict do nothing;
