#!/usr/bin/env python3
"""Seed IDENTICAL demo dashboard data for the whole team (shared Supabase DB).

Everyone pulls the repo and runs their own backend against the same database, so
seeding each teammate's account once (in the shared DB) is enough — whoever logs
in sees the same populated dashboard and can suggest changes.

For each target account this seeds, against one demo exam (DEMO_EXAM):
  - a switch to the demo exam (so mock-list + dashboard align),
  - ~10 completed attempts with an improving trend (attempt_results + section/
    skill/question breakdowns, error-typed),
  - knowledge_components taken from the exam's REAL syllabus chapters,
  - per-concept mastery (BKT + decay), per-attempt insights, and a student profile.
All rows are is_dummy=true / generated_by='crafted' and use a FIXED RNG seed, so
every account's numbers are identical (easy to review together).

Usage:
  python scripts/seed_demo_all.py                 # all completed-profile users
  python scripts/seed_demo_all.py a@x.com b@y.com  # only these emails
  DEMO_EXAM=CAT python scripts/seed_demo_all.py     # different exam
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
import statistics
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services import analytics  # noqa: E402

DEMO_EXAM = os.environ.get("DEMO_EXAM", "JEE_MAINS")
N_ATTEMPTS = 10
Q_PER_ATTEMPT = 42
SEED = 4207


def get_dsn() -> str | None:
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        return dsn
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    return None


def craft_attempt_insight(idx: int, n: int, accuracy: float, behavior: dict, weak_subject: str) -> dict:
    arche = behavior["behavior_archetype"]
    careless_share = behavior["careless_share"]
    guess_rate = behavior["guess_rate"]
    improving = idx >= n - 3
    trend = "up from your early mocks" if improving else "still finding your rhythm"
    if careless_share >= 45:
        gap = (f"Most of your lost marks are **careless** — fast wrong answers in {weak_subject}. "
               f"A pacing/checking problem, not a knowledge gap.")
        action = f"Redo a 15-question {weak_subject} set with a strict 'read twice before marking' rule."
        headline = f"You know more than your score shows — {int(careless_share)}% of misses were careless."
    elif guess_rate >= 18:
        gap = f"You are guessing on hard {weak_subject} items ({guess_rate:.0f}% guess rate) — luck masks a gap."
        action = f"Do 10 timed {weak_subject} questions, marking confidence first; review every low-confidence one."
        headline = f"Guessing is hiding your true {weak_subject} gaps."
    else:
        gap = f"Your misses in {weak_subject} were slow and wrong — a genuine **conceptual** gap."
        action = f"Re-derive the core {weak_subject} concept from scratch, then take a 10-question retrieval quiz on it."
        headline = f"{weak_subject} is your highest-leverage fix this attempt."
    return {
        "headline": headline,
        "goal": "Lift overall accuracy toward 85% while keeping pace under control.",
        "current_status": (f"You scored {accuracy:.0f}% ({trend}). Behaviour archetype: {arche}. "
                           f"Section accuracy is uneven — {weak_subject} is dragging the total."),
        "gap_diagnosis": gap,
        "calibration_note": "You tend to move fastest on the questions you get wrong — over-confidence on tricky items.",
        "next_actions": [action, "Log the one idea you missed most and re-test it in 3 days."],
        "recommended_method": "Active retrieval + spaced review (today, +3 days, +1 week) — not re-reading.",
        "behavior_archetype": arche,
        "pacing_note": f"Avg time/question {behavior['avg_time_ms'] or 0} ms; watch the fast-wrong pattern.",
        "negative_marking_loss": behavior["negative_marking_loss"],
        "guess_rate": guess_rate,
        "calibration_gap": round(min(25.0, careless_share / 3 + guess_rate / 2), 2),
    }


async def main() -> int:
    dsn = get_dsn()
    if not dsn:
        print("DATABASE_URL not set")
        return 2
    emails = sys.argv[1:]

    conn = await asyncpg.connect(dsn, statement_cache_size=0, server_settings={"search_path": "mock_db,public"})
    try:
        exam = await conn.fetchrow("select id, name from catalog_exams where code=$1", DEMO_EXAM)
        if not exam:
            print(f"DEMO_EXAM {DEMO_EXAM} not found")
            return 1
        exam_id = exam["id"]
        subjects = await conn.fetch(
            "select id, name from syllabus_subjects where catalog_exam_id=$1 order by position", exam_id)
        subj_names = [s["name"] for s in subjects]
        skills = [(r["code"], r["name"]) for r in await conn.fetch(
            "select code, name from skills where catalog_exam_id=$1 order by name limit 12", exam_id)] or [(None, "General")]
        mock_ids = [r["id"] for r in await conn.fetch(
            "select id from mock_tests where catalog_exam_id=$1 and scope in ('full','subject') order by position limit 20",
            exam_id)]

        # --- knowledge_components from the exam's REAL chapters (shared, idempotent) ---
        subject_kcs: dict[str, list[str]] = {}
        kc_id: dict[str, str] = {}
        kc_name: dict[str, str] = {}
        kc_rows = []
        for s in subjects:
            chs = await conn.fetch(
                "select code, name from syllabus_chapters where subject_id=$1 order by position limit 6", s["id"])
            if not chs:
                chs = [{"code": f"KC_{DEMO_EXAM}_{s['name'][:6].upper()}", "name": s["name"]}]
            codes = []
            for ch in chs:
                code = ch["code"]
                codes.append(code)
                kc_name[code] = ch["name"]
                kid = uuid.uuid4()
                kc_id[code] = kid
                kc_rows.append((kid, s["id"], DEMO_EXAM, code, ch["name"]))
            subject_kcs[s["name"]] = codes
        # insert KCs, skipping ones already present (shared across users/runs)
        await conn.executemany(
            """insert into knowledge_components (id, subject_id, catalog_exam_code, code, name, kc_type, source)
               values ($1,$2,$3,$4,$5,'concept','seed') on conflict (code) do nothing""", kc_rows)
        # resolve ids for any KCs that already existed
        existing = {r["code"]: r["id"] for r in await conn.fetch(
            "select code, id from knowledge_components where catalog_exam_code=$1", DEMO_EXAM)}
        kc_id.update(existing)

        # gap vs strong split per subject (for realistic mastery spread)
        gap_codes = {s: c[:max(1, math.ceil(len(c) * 0.35))] for s, c in subject_kcs.items()}
        strong_codes = {s: (c[max(1, math.ceil(len(c) * 0.35)):] or c) for s, c in subject_kcs.items()}

        # --- target users ---
        if emails:
            users = await conn.fetch("select id, email from users where email = any($1::text[])", emails)
        else:
            users = await conn.fetch("select id, email from users where profile_completed = true")

        now = datetime.now(tz=timezone.utc)
        AR, SEC, SKL, QST, SCM, AINS, SINS = [], [], [], [], [], [], []
        stream_rows = []

        for u in users:
            uid = u["id"]
            rng = random.Random(SEED)  # SAME seed per user => identical data

            # clear existing dummy data for this user
            await conn.execute("delete from attempt_results where user_id=$1", uid)
            await conn.execute("delete from student_concept_mastery where user_id=$1", uid)
            await conn.execute("delete from student_insights where user_id=$1", uid)

            # ensure current stream = demo exam (append a switch + mirror)
            cur = await conn.fetchval(
                "select catalog_exam_code from user_stream_selections where user_id=$1 order by created_at desc limit 1", uid)
            if cur != DEMO_EXAM:
                stream_rows.append((uid,))
                await conn.execute(
                    """insert into user_stream_selections (user_id, category_code, catalog_exam_code, source)
                       select $1, mc.code, $2, 'switch' from catalog_exams ce join mock_categories mc on mc.id=ce.category_id
                       where ce.code=$2""", uid, DEMO_EXAM)
                await conn.execute(
                    """update users set catalog_exam_code=$2,
                         mock_category_code=(select mc.code from catalog_exams ce join mock_categories mc on mc.id=ce.category_id where ce.code=$2)
                       where id=$1""", uid, DEMO_EXAM)

            kc_events: dict[str, list[tuple[datetime, bool]]] = {}
            gap_rr: dict[str, int] = {}
            strong_rr: dict[str, int] = {}

            for i in range(N_ATTEMPTS):
                ar_id = uuid.uuid4()
                base = 0.52 + 0.34 * i / (N_ATTEMPTS - 1)
                acc = min(0.95, max(0.35, base + rng.uniform(-0.05, 0.05)))
                total = Q_PER_ATTEMPT
                attempted = rng.randint(int(total * 0.85), total)
                correct = round(attempted * acc)
                wrong = attempted - correct
                skipped = total - attempted
                score = round(correct - 0.25 * wrong, 2)
                percentile = round(min(99.5, 40 + base * 60 + rng.uniform(-3, 3)), 2)
                accuracy_pct = round(100 * correct / attempted, 2) if attempted else 0
                days_ago = (N_ATTEMPTS - i) * 6 + rng.randint(0, 3)
                started = now - timedelta(days=days_ago, minutes=rng.randint(0, 300))
                dur = rng.randint(2400, 7200)
                submitted = started + timedelta(seconds=dur)
                AR.append((ar_id, uid, rng.choice(mock_ids) if mock_ids else None, DEMO_EXAM, started, submitted,
                           dur, total, attempted, correct, wrong, skipped, score, float(total), percentile,
                           accuracy_pct, True))

                per_sec = total // len(subj_names)
                for pos, sec in enumerate(subj_names):
                    s_acc = min(0.97, max(0.3, acc + rng.uniform(-0.15, 0.15)))
                    s_att = rng.randint(int(per_sec * 0.85), per_sec)
                    s_cor = round(s_att * s_acc)
                    SEC.append((uuid.uuid4(), ar_id, sec, per_sec, s_cor, s_att - s_cor, per_sec - s_att,
                                round(s_cor - 0.25 * (s_att - s_cor), 2),
                                round(100 * s_cor / s_att, 2) if s_att else 0, rng.randint(35000, 95000), pos))

                for code, name in skills:
                    sk_tot = rng.randint(3, 8)
                    sk_acc = min(0.98, max(0.25, acc + rng.uniform(-0.2, 0.2)))
                    sk_cor = round(sk_tot * sk_acc)
                    SKL.append((uuid.uuid4(), ar_id, code, name, sk_tot, sk_cor,
                                round(100 * sk_cor / sk_tot, 2), rng.randint(30000, 110000)))

                median_ms = 60000
                for qn in range(1, total + 1):
                    sec = subj_names[(qn - 1) % len(subj_names)]
                    is_correct = None if qn > attempted else (rng.random() < acc)
                    tms = rng.randint(15000, 180000)
                    diff = rng.choice(["easy", "medium", "hard"])
                    etype = analytics.classify_error(is_correct, tms, diff, median_ms)
                    # assign concept: wrong/unattempted -> gap concept; correct -> strong
                    if is_correct is not True or rng.random() < 0.2:
                        pool, rr = gap_codes[sec], gap_rr
                    else:
                        pool, rr = strong_codes[sec], strong_rr
                    j = rr.get(sec, 0); code = pool[j % len(pool)]; rr[sec] = j + 1
                    QST.append((uuid.uuid4(), ar_id, qn, sec, skills[(qn - 1) % len(skills)][0], code,
                                etype, is_correct, tms, diff, rng.random() < 0.12))
                    if is_correct is not None:
                        kc_events.setdefault(code, []).append((submitted, bool(is_correct)))

            # mastery per concept
            subject_mastery: dict[str, list[float]] = {}
            scm_for_user = []
            for code, events in kc_events.items():
                events.sort(key=lambda e: e[0])
                p = 0.35; last_correct = None; wrong = 0
                for when, ok in events:
                    p = analytics.bkt_posterior(p, ok)
                    if ok:
                        last_correct = when
                    else:
                        wrong += 1
                days_since = (now - last_correct).days if last_correct else None
                retention = analytics.decay_retention(p, days_since)
                prio = analytics.gap_priority(retention)
                n_opp = len(events)
                SCM.append((uuid.uuid4(), uid, kc_id[code], round(p, 3), n_opp, retention, last_correct, None,
                            round(min(1.0, 0.4 if wrong else 0), 3), round(min(1.0, wrong / n_opp), 3) if n_opp else 0,
                            None, None, prio, True))
                scm_for_user.append((code, retention))
                subj = next((s for s in subj_names if code in subject_kcs.get(s, [])), None)
                if subj:
                    subject_mastery.setdefault(subj, []).append(retention)

            weak_subject = (min(subject_mastery, key=lambda s: statistics.mean(subject_mastery[s]))
                            if subject_mastery else subj_names[0])
            strong_subject = (max(subject_mastery, key=lambda s: statistics.mean(subject_mastery[s]))
                              if subject_mastery else subj_names[-1])

            # attempt insights
            user_ars = [r for r in AR if r[1] == uid]
            for idx, ar in enumerate(user_ars):
                arows = [{"is_correct": q[7], "error_type": q[6], "time_spent_ms": q[8]} for q in QST if q[1] == ar[0]]
                behavior = analytics.attempt_behavior(arows)
                ins = craft_attempt_insight(idx, len(user_ars), float(ar[15] or 0), behavior, weak_subject)
                AINS.append((uuid.uuid4(), ar[0], ins["headline"], ins["goal"], ins["current_status"],
                             ins["gap_diagnosis"], ins["calibration_note"], json.dumps(ins["next_actions"]),
                             ins["recommended_method"], ins["behavior_archetype"], ins["pacing_note"],
                             ins["negative_marking_loss"], ins["guess_rate"], ins["calibration_gap"], "crafted", None, True))

            # student profile
            latest_acc = float(user_ars[-1][15] or 0) if user_ars else 0
            weakest = sorted(scm_for_user, key=lambda x: x[1])[:3]
            strongest = sorted(scm_for_user, key=lambda x: x[1], reverse=True)[:3]
            gaps = [kc_name[c] for c, _ in weakest]
            strengths = [kc_name[c] for c, _ in strongest]
            predicted = round(min(95, latest_acc + 4), 1)
            summary = (f"Across {N_ATTEMPTS} mocks your accuracy has climbed to about {latest_acc:.0f}%, driven mostly "
                       f"by {strong_subject}. Your persistent drag is {weak_subject} and a habit of rushing the questions "
                       f"you get wrong. Fix the {gaps[0] if gaps else weak_subject} gap and tighten pacing to clear the next band.")
            plan = [
                {"step": 1, "focus": gaps[0] if gaps else weak_subject,
                 "action": "Re-derive the concept, then take a 10-question retrieval quiz today and again in 3 days."},
                {"step": 2, "focus": "Careless control",
                 "action": "Do one timed set with a 'read twice, then commit' rule; target <5% careless misses."},
                {"step": 3, "focus": gaps[1] if len(gaps) > 1 else "Mixed revision",
                 "action": "Interleave this weak topic with a strong one so retrieval stays effortful."},
            ]
            SINS.append((uid, DEMO_EXAM, summary, json.dumps(strengths), json.dumps(gaps),
                         predicted, round(predicted - 6, 1), round(predicted + 4, 1), json.dumps(plan)))

        # --- bulk insert everything ---
        await conn.executemany(
            """insert into attempt_results (id,user_id,mock_test_id,catalog_exam_code,started_at,submitted_at,
               duration_seconds,total_questions,attempted,correct,wrong,skipped,score,max_score,percentile,accuracy_pct,is_dummy)
               values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)""", AR)
        await conn.executemany(
            """insert into attempt_section_results (id,attempt_result_id,section_name,total,correct,wrong,skipped,
               score,accuracy_pct,avg_time_ms,position) values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""", SEC)
        await conn.executemany(
            """insert into attempt_skill_results (id,attempt_result_id,skill_code,skill_name,total,correct,accuracy_pct,avg_time_ms)
               values ($1,$2,$3,$4,$5,$6,$7,$8)""", SKL)
        await conn.executemany(
            """insert into attempt_question_results (id,attempt_result_id,question_no,section_name,skill_code,kc_code,
               error_type,is_correct,time_spent_ms,difficulty,marked_for_review)
               values ($1,$2,$3,$4,$5,$6,$7::mock_db.error_type,$8,$9,$10,$11)""", QST)
        await conn.executemany(
            """insert into student_concept_mastery (id,user_id,kc_id,p_mastery,n_opportunities,retention_probability,
               last_correct_at,next_review_due,careless_rate,conceptual_gap_score,avg_time_z,dominant_misconception,gap_priority,is_dummy)
               values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)""", SCM)
        await conn.executemany(
            """insert into attempt_insights (id,attempt_result_id,headline,goal,current_status,gap_diagnosis,calibration_note,
               next_actions,recommended_method,behavior_archetype,pacing_note,negative_marking_loss,guess_rate,calibration_gap,
               generated_by,model,is_dummy)
               values ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11,$12,$13,$14,$15::mock_db.insight_source,$16,$17)""", AINS)
        await conn.executemany(
            """insert into student_insights (user_id,stream_catalog_exam_code,summary,persistent_strengths,persistent_gaps,
               predicted_score,predicted_band_low,predicted_band_high,study_plan,generated_by,model,is_dummy)
               values ($1,$2,$3,$4::jsonb,$5::jsonb,$6,$7,$8,$9::jsonb,'crafted',null,true)""", SINS)

        print(f"Demo exam: {DEMO_EXAM} ({exam['name']})")
        print(f"Seeded {len(users)} accounts | KCs={len(kc_rows)} attempts={len(AR)} "
              f"questions={len(QST)} mastery={len(SCM)} attempt_insights={len(AINS)} profiles={len(SINS)}")
        print("Accounts:", ", ".join(u["email"] for u in users))
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
