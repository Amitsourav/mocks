-- ============================================================================
-- Migration 0002 — enable Row-Level Security (deny-by-default for client roles)
--
-- Architecture: all data access goes through the FastAPI backend, which connects
-- with a privileged role (service_role / postgres) that BYPASSES RLS. The public
-- `anon` and `authenticated` roles (Supabase client libraries) must have NO direct
-- access to mock_db — especially the secret answer keys
-- (question_options.is_correct, questions.numeric_answer_key).
--
-- Enabling RLS with no permissive policies denies all access to anon/authenticated
-- while leaving the backend's privileged connection unaffected. If, later, the
-- frontend is allowed to read catalog data directly via Supabase, add explicit
-- SELECT policies to the specific safe tables/columns only.
-- ============================================================================

do $$
declare
  t text;
  tables text[] := array[
    'examinations','exam_modules','exam_sections','subjects','users',
    'media_assets','stimuli','questions','question_options','skills',
    'question_skill_tags','attempts','attempt_sections','student_answers',
    'question_events'
  ];
begin
  foreach t in array tables loop
    -- ENABLE (not FORCE): anon/authenticated are subject to RLS and, with no
    -- permissive policies, get zero access. The table owner and service_role
    -- (BYPASSRLS) — i.e. the FastAPI backend connection — are unaffected.
    execute format('alter table mock_db.%I enable row level security;', t);
  end loop;
end$$;
