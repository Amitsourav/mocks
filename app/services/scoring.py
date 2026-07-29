"""Score a submitted attempt into the report tables.

Runs after `submit_attempt`. Grades each saved answer against the frozen paper's
answer key, then writes:
  - attempt_results               (the headline: score, accuracy, percentile…)
  - attempt_section_results       (per section)
  - attempt_skill_results         (per skill)
  - attempt_question_results      (per question: right/wrong, error type)

Idempotent: a second call for an already-scored attempt returns the existing
result id and writes nothing. dMAT has no negative marking, but per-question
`negative_marks` is honoured if a future exam sets it.
"""

from __future__ import annotations

import json
from uuid import UUID

import asyncpg

from app.services.analytics import classify_error


async def refresh_insight(conn, user_id: UUID, stream_code: str | None) -> None:
    """Rebuild the student's dashboard 'insight' from their real results.

    Heuristic (not AI): strongest/weakest sections, strengths/gaps by skill, a
    predicted band and a short study plan. The dashboard gates its whole view on
    a non-null insight, so every scored student needs one — even before AI
    narratives exist. Aggregated across all the user's attempts.
    """
    agg = await conn.fetchrow(
        "select count(*) n, round(avg(accuracy_pct), 1) acc from attempt_results where user_id = $1",
        user_id,
    )
    if not agg or not agg["n"]:
        return
    skills = await conn.fetch(
        """select sr.skill_name name, sum(sr.correct)::float c, sum(sr.total)::float t
           from attempt_skill_results sr join attempt_results ar on ar.id = sr.attempt_result_id
           where ar.user_id = $1 group by sr.skill_name having sum(sr.total) > 0""",
        user_id,
    )
    secs = await conn.fetch(
        """select sr.section_name name, sum(sr.correct)::float c, sum(sr.total)::float t
           from attempt_section_results sr join attempt_results ar on ar.id = sr.attempt_result_id
           where ar.user_id = $1 group by sr.section_name having sum(sr.total) > 0""",
        user_id,
    )
    by_skill = sorted(((r["name"], r["c"] / r["t"]) for r in skills), key=lambda x: x[1])
    gaps = [n for n, a in by_skill if a < 0.5][:4]
    strengths = [n for n, a in reversed(by_skill) if a >= 0.6][:4]
    by_sec = sorted(((r["name"], r["c"] / r["t"]) for r in secs), key=lambda x: x[1])
    weak = by_sec[0][0] if by_sec else None
    strong = by_sec[-1][0] if by_sec else None
    acc = float(agg["acc"] or 0)
    n = agg["n"]
    summary = (
        f"Across {n} mock{'s' if n != 1 else ''} you're averaging {acc:.0f}% accuracy."
        + (f" {strong} is your strongest section" if strong else "")
        + (f", while {weak} needs the most work." if weak else ".")
    )
    focus = gaps[0] if gaps else (weak or "Mixed revision")
    plan = [
        {"step": 1, "focus": focus,
         "action": "Re-derive the core concept, then take a short retrieval quiz today and again in 3 days."},
        {"step": 2, "focus": "Pacing & review",
         "action": "Do one timed set with a 'read twice, then commit' rule to cut avoidable mistakes."},
    ]
    if len(gaps) > 1:
        plan.append({"step": 3, "focus": gaps[1],
                     "action": "Interleave this weak topic with a strong one so practice stays effortful."})
    await conn.execute("delete from student_insights where user_id = $1", user_id)
    await conn.execute(
        """insert into student_insights
           (user_id, stream_catalog_exam_code, summary, persistent_strengths, persistent_gaps,
            predicted_score, predicted_band_low, predicted_band_high, study_plan, generated_by, model, is_dummy)
           values ($1,$2,$3,$4::jsonb,$5::jsonb,$6,$7,$8,$9::jsonb,'crafted',null,false)""",
        user_id, stream_code, summary, json.dumps(strengths), json.dumps(gaps),
        round(acc, 1), round(max(0.0, acc - 6), 1), round(min(100.0, acc + 4), 1), json.dumps(plan),
    )


async def score_attempt(pool: asyncpg.Pool, user_id: UUID, attempt_id: UUID) -> UUID | None:
    """Grade a submitted attempt and materialise its report. Returns the new (or
    existing) attempt_result_id, or None if the attempt isn't the user's."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            att = await conn.fetchrow(
                """select a.id, a.user_id, a.started_at, a.submitted_at, u.catalog_exam_code
                   from attempts a join users u on u.id = a.user_id where a.id = $1""",
                attempt_id,
            )
            if att is None or att["user_id"] != user_id:
                return None

            existing = await conn.fetchval(
                "select id from attempt_results where engine_attempt_id = $1", attempt_id
            )
            if existing is not None:
                return existing

            # Frozen paper: each question with its section, difficulty, marks and
            # correct option.
            qrows = await conn.fetch(
                """
                select aq.position as qno, q.id as qid, q.difficulty,
                       coalesce(q.marks, 1) as marks, coalesce(q.negative_marks, 0) as neg,
                       s.name as section_name, s.position as section_pos,
                       (select o.id from question_options o
                        where o.question_id = q.id and o.is_correct limit 1) as correct_opt
                from attempt_questions aq
                join questions q on q.id = aq.question_id
                join exam_sections s on s.id = aq.section_id
                where aq.attempt_id = $1
                order by aq.position
                """,
                attempt_id,
            )
            if not qrows:
                return None

            answers = {
                r["question_id"]: r
                for r in await conn.fetch(
                    "select question_id, selected_option_id, is_marked_for_review, time_spent_ms "
                    "from student_answers where attempt_id = $1",
                    attempt_id,
                )
            }
            skills_by_q: dict[UUID, list[tuple[str, str]]] = {}
            for r in await conn.fetch(
                """select qst.question_id, sk.code, sk.name
                   from question_skill_tags qst join skills sk on sk.id = qst.skill_id
                   where qst.question_id = any($1::uuid[])""",
                [q["qid"] for q in qrows],
            ):
                skills_by_q.setdefault(r["question_id"], []).append((r["code"], r["name"]))

            correct = wrong = skipped = 0
            score = max_score = 0.0
            sec: dict[str, dict] = {}
            skl: dict[str, dict] = {}
            q_rows: list[tuple] = []

            for q in qrows:
                a = answers.get(q["qid"])
                marks, neg = float(q["marks"]), float(q["neg"])
                max_score += marks
                sel = a["selected_option_id"] if a else None
                if sel is None:
                    is_corr = None
                    skipped += 1
                elif sel == q["correct_opt"]:
                    is_corr = True
                    correct += 1
                    score += marks
                else:
                    is_corr = False
                    wrong += 1
                    score -= neg
                tms = a["time_spent_ms"] if a else None
                err = classify_error(is_corr, tms, q["difficulty"], None)
                first_skill = skills_by_q.get(q["qid"], [(None, None)])[0]
                q_rows.append((
                    q["qno"], q["section_name"], first_skill[0], is_corr, tms,
                    q["difficulty"], bool(a["is_marked_for_review"]) if a else False, err,
                ))

                s = sec.setdefault(q["section_name"], {
                    "pos": q["section_pos"], "total": 0, "correct": 0, "wrong": 0,
                    "skipped": 0, "score": 0.0, "time": [],
                })
                s["total"] += 1
                if is_corr is None:
                    s["skipped"] += 1
                elif is_corr:
                    s["correct"] += 1
                    s["score"] += marks
                else:
                    s["wrong"] += 1
                if tms:
                    s["time"].append(tms)

                for code, name in skills_by_q.get(q["qid"], []):
                    k = skl.setdefault(code, {"name": name, "total": 0, "correct": 0, "time": []})
                    k["total"] += 1
                    if is_corr:
                        k["correct"] += 1
                    if tms:
                        k["time"].append(tms)

            attempted = correct + wrong
            accuracy = round(100 * correct / attempted, 2) if attempted else 0.0
            duration = (
                int((att["submitted_at"] - att["started_at"]).total_seconds())
                if att["submitted_at"] and att["started_at"] else None
            )

            # Percentile within the same exam-stream cohort (best score per user).
            percentile = await conn.fetchval(
                """
                with best as (
                    select distinct on (user_id) user_id, score
                    from attempt_results
                    where catalog_exam_code = $1 and score is not null
                    order by user_id, score desc
                )
                select case when count(*) = 0 then null
                       else round(100.0 * count(*) filter (where score <= $2) / count(*), 2) end
                from best
                """,
                att["catalog_exam_code"], score,
            )

            ar_id = await conn.fetchval(
                """
                insert into attempt_results
                    (user_id, mock_test_id, catalog_exam_code, engine_attempt_id, started_at,
                     submitted_at, duration_seconds, total_questions, attempted, correct, wrong,
                     skipped, score, max_score, percentile, accuracy_pct, is_dummy)
                values ($1,null,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,false)
                returning id
                """,
                user_id, att["catalog_exam_code"], attempt_id, att["started_at"],
                att["submitted_at"], duration, len(qrows), attempted, correct, wrong,
                skipped, score, max_score, percentile, accuracy,
            )

            # Mark the graded answers (source of truth stays the report tables).
            await conn.execute(
                """update student_answers sa set is_correct = (sa.selected_option_id = qo.id)
                   from question_options qo
                   where sa.attempt_id = $1 and qo.question_id = sa.question_id and qo.is_correct""",
                attempt_id,
            )

            await conn.executemany(
                """insert into attempt_section_results
                   (attempt_result_id, section_name, total, correct, wrong, skipped, score,
                    accuracy_pct, avg_time_ms, position)
                   values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)""",
                [(
                    ar_id, name, s["total"], s["correct"], s["wrong"], s["skipped"], s["score"],
                    round(100 * s["correct"] / (s["correct"] + s["wrong"]), 2)
                    if (s["correct"] + s["wrong"]) else 0.0,
                    round(sum(s["time"]) / len(s["time"])) if s["time"] else None,
                    s["pos"],
                ) for name, s in sec.items()],
            )
            await conn.executemany(
                """insert into attempt_skill_results
                   (attempt_result_id, skill_code, skill_name, total, correct, accuracy_pct, avg_time_ms)
                   values ($1,$2,$3,$4,$5,$6,$7)""",
                [(
                    ar_id, code, k["name"], k["total"], k["correct"],
                    round(100 * k["correct"] / k["total"], 2) if k["total"] else 0.0,
                    round(sum(k["time"]) / len(k["time"])) if k["time"] else None,
                ) for code, k in skl.items()],
            )
            await conn.executemany(
                """insert into attempt_question_results
                   (attempt_result_id, question_no, section_name, skill_code, is_correct,
                    time_spent_ms, difficulty, marked_for_review, error_type)
                   values ($1,$2,$3,$4,$5,$6,$7,$8,$9::mock_db.error_type)""",
                [(ar_id, *row) for row in q_rows],
            )
            # Refresh the dashboard insight so the student isn't stuck on the empty
            # state (the dashboard requires a non-null insight to render).
            await refresh_insight(conn, user_id, att["catalog_exam_code"])
            return ar_id
