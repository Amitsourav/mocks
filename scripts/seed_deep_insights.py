#!/usr/bin/env python3
"""Seed the deep-insight layer with CRAFTED sample data for the demo account.

Reuses the demo's existing attempts + question rows to:
  1. seed knowledge_components (concepts) for the stream's subjects,
  2. classify each question row into an error_type + assign a concept (kc_code),
  3. compute per-concept mastery (BKT + decay) with ranked gaps,
  4. write crafted per-attempt insights + a current student profile.

Everything matches the OpenRouter AI output shape exactly (generated_by='crafted',
is_dummy=true), so the live pipeline swaps in with zero schema/UI change.

Run:  .venv/bin/python scripts/seed_deep_insights.py [email]
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services import analytics  # noqa: E402

DEFAULT_EMAIL = "prsuman25@gmail.com"

# Realistic Class-7 concept sets, keyed by a subject-name keyword.
KC_BY_KEYWORD: dict[str, list[tuple[str, str, str]]] = {
    "math": [
        ("C7_MATH_INTEGERS", "Operations on Integers", "procedure"),
        ("C7_MATH_FRACTIONS", "Fractions and Decimals", "procedure"),
        ("C7_MATH_EQUATIONS", "Simple Linear Equations", "concept"),
        ("C7_MATH_ANGLES", "Lines and Angles", "concept"),
        ("C7_MATH_RATIO", "Ratio and Proportion", "concept"),
        ("C7_MATH_AREA", "Perimeter and Area", "procedure"),
    ],
    "science": [
        ("C7_SCI_NUTRITION", "Nutrition in Plants and Animals", "fact"),
        ("C7_SCI_HEAT", "Heat and Temperature", "concept"),
        ("C7_SCI_ACIDS", "Acids, Bases and Salts", "concept"),
        ("C7_SCI_MOTION", "Motion and Time", "concept"),
        ("C7_SCI_ELECTRIC", "Electric Current and Its Effects", "concept"),
    ],
    "social": [
        ("C7_SST_MEDIEVAL", "Medieval Indian History", "fact"),
        ("C7_SST_ENV", "Environment and Our Surroundings", "concept"),
        ("C7_SST_CIVICS", "Democracy and Equality", "concept"),
        ("C7_SST_MARKETS", "Markets Around Us", "concept"),
    ],
    "english": [
        ("C7_ENG_RC", "Reading Comprehension", "concept"),
        ("C7_ENG_GRAMMAR", "Grammar and Tenses", "procedure"),
        ("C7_ENG_VOCAB", "Vocabulary", "fact"),
        ("C7_ENG_WRITING", "Writing Skills", "procedure"),
    ],
}


def kc_list_for(subject_name: str) -> list[tuple[str, str, str]]:
    n = subject_name.lower()
    if "math" in n:
        return KC_BY_KEYWORD["math"]
    if "social" in n:
        return KC_BY_KEYWORD["social"]
    if "science" in n:
        return KC_BY_KEYWORD["science"]
    if "english" in n:
        return KC_BY_KEYWORD["english"]
    # fallback generic
    slug = "".join(c for c in n.upper() if c.isalnum())[:10] or "GEN"
    return [(f"C7_{slug}_{i}", f"{subject_name} — Topic {i}", "concept") for i in range(1, 5)]


def get_dsn() -> str | None:
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        return dsn
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    return None


def craft_attempt_insight(idx: int, n: int, accuracy: float, behavior: dict, weak_subject: str) -> dict:
    """A believable, process-level per-attempt narrative (matches the AI shape)."""
    arche = behavior["behavior_archetype"]
    careless_share = behavior["careless_share"]
    guess_rate = behavior["guess_rate"]
    improving = idx >= n - 3
    trend = "up from your early mocks" if improving else "still finding your rhythm"

    if careless_share >= 45:
        gap = (f"Most of your lost marks are **careless** — fast wrong answers in {weak_subject}. "
               f"This is a pacing/checking problem, not a knowledge gap.")
        action = f"Redo a 15-question {weak_subject} set with a strict 'read twice before marking' rule."
        headline = f"You know more than your score shows — {int(careless_share)}% of misses were careless."
    elif guess_rate >= 18:
        gap = (f"You are guessing on hard {weak_subject} items ({guess_rate:.0f}% guess rate) — "
               f"lucky hits mask a real gap.")
        action = f"Do 10 timed {weak_subject} questions and mark your confidence before each; review every low-confidence one."
        headline = f"Guessing is hiding your true {weak_subject} gaps."
    else:
        gap = (f"Your misses in {weak_subject} were slow and wrong — a genuine **conceptual** gap, "
               f"not carelessness.")
        action = f"Re-derive the core {weak_subject} concept from scratch, then take a 10-question retrieval quiz on it."
        headline = f"{weak_subject} is your highest-leverage fix this attempt."

    return {
        "headline": headline,
        "goal": "Lift overall accuracy toward 85% while keeping pace under control.",
        "current_status": (f"You scored {accuracy:.0f}% ({trend}). Behaviour archetype: {arche}. "
                           f"Section accuracy is uneven — {weak_subject} is dragging the total."),
        "gap_diagnosis": gap,
        "calibration_note": ("You tend to move fastest on the questions you get wrong — a sign of "
                             "over-confidence on tricky items."),
        "next_actions": [action, "Log the one formula/idea you missed most and re-test it in 3 days."],
        "recommended_method": "Active retrieval + spaced review (today, +3 days, +1 week) — not re-reading.",
        "behavior_archetype": arche,
        "pacing_note": f"Avg time/question {behavior['avg_time_ms'] or 0} ms; watch the fast-wrong pattern.",
        "negative_marking_loss": behavior["negative_marking_loss"],
        "guess_rate": guess_rate,
        "calibration_gap": round(min(25.0, careless_share / 3 + guess_rate / 2), 2),
    }


async def main() -> int:
    email = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EMAIL
    dsn = get_dsn()
    if not dsn:
        print("DATABASE_URL not set")
        return 2

    conn = await asyncpg.connect(dsn, statement_cache_size=0, server_settings={"search_path": "mock_db,public"})
    try:
        user = await conn.fetchrow("select id from users where email=$1", email)
        if not user:
            print(f"No user {email}")
            return 1
        user_id = user["id"]
        # Key off the exam the ATTEMPTS belong to (analytics describe past attempts),
        # NOT the user's current stream — the two can differ after a stream switch.
        row = await conn.fetchrow(
            "select catalog_exam_code, count(*) c from attempt_results where user_id=$1 "
            "group by catalog_exam_code order by c desc limit 1", user_id)
        if not row:
            print(f"{email} has no attempts to build insights from")
            return 1
        exam_code = row["catalog_exam_code"]
        exam = await conn.fetchrow("select id from catalog_exams where code=$1", exam_code)
        subjects = await conn.fetch(
            "select id, name from syllabus_subjects where catalog_exam_id=$1 order by position", exam["id"])

        # --- clear prior sample for this user ---
        await conn.execute("delete from student_concept_mastery where user_id=$1", user_id)
        await conn.execute("delete from student_insights where user_id=$1", user_id)
        await conn.execute(
            "delete from attempt_insights where attempt_result_id in (select id from attempt_results where user_id=$1)",
            user_id)
        # Clear our seeded concept set (all use C7_* codes) regardless of prior tag.
        await conn.execute(r"delete from knowledge_components where code like 'C7\_%' escape '\'")

        # --- seed knowledge_components ---
        kc_id: dict[str, str] = {}
        subject_kcs: dict[str, list[str]] = {}   # subject name -> [kc_code]
        kc_rows = []
        for s in subjects:
            codes = []
            for code, name, ktype in kc_list_for(s["name"]):
                kid = uuid.uuid4()
                kc_id[code] = kid
                codes.append(code)
                kc_rows.append((kid, s["id"], exam_code, code, name, ktype, "seed"))
            subject_kcs[s["name"]] = codes
        await conn.executemany(
            """insert into knowledge_components (id, subject_id, catalog_exam_code, code, name, kc_type, source)
               values ($1,$2,$3,$4,$5,$6::mock_db.kc_type,$7::mock_db.kc_source)""", kc_rows)

        # --- load attempts + question rows ---
        attempts = await conn.fetch(
            "select id, submitted_at, accuracy_pct from attempt_results where user_id=$1 order by submitted_at", user_id)
        qrows = await conn.fetch(
            """select q.id, q.attempt_result_id, q.section_name, q.is_correct, q.time_spent_ms, q.difficulty,
                      ar.submitted_at
               from attempt_question_results q join attempt_results ar on ar.id = q.attempt_result_id
               where ar.user_id=$1 order by ar.submitted_at, q.question_no""", user_id)

        all_times = [r["time_spent_ms"] for r in qrows if r["time_spent_ms"] is not None]
        median_ms = statistics.median(all_times) if all_times else None

        # Split each subject's concepts into a "gap" subset and a "strong" subset,
        # then route WRONG answers toward the gap concepts (and correct answers
        # mostly to the strong ones). This gives realistic mastery SPREAD instead
        # of every concept converging to the ceiling.
        import math as _math
        import random as _random
        rng = _random.Random(99)
        gap_codes: dict[str, list[str]] = {}
        strong_codes: dict[str, list[str]] = {}
        for subj, codes in subject_kcs.items():
            k = max(1, _math.ceil(len(codes) * 0.35))
            gap_codes[subj] = codes[:k]
            strong_codes[subj] = codes[k:] or codes[:k]

        # --- classify each question row: error_type + kc_code ---
        gap_rr: dict[str, int] = {}
        strong_rr: dict[str, int] = {}
        updates = []                       # (error_type, kc_code, id)
        kc_events: dict[str, list[tuple[datetime, bool]]] = {}   # kc_code -> [(when, correct)]
        for r in qrows:
            etype = analytics.classify_error(r["is_correct"], r["time_spent_ms"], r["difficulty"], median_ms)
            subj = r["section_name"] if r["section_name"] in subject_kcs else next(iter(subject_kcs))
            if r["is_correct"] is not True or rng.random() < 0.2:
                pool, rr = gap_codes[subj], gap_rr       # wrong/unattempted (+20% of correct) -> gap concepts
            else:
                pool, rr = strong_codes[subj], strong_rr  # correct -> strong concepts
            i = rr.get(subj, 0)
            code = pool[i % len(pool)]
            rr[subj] = i + 1
            updates.append((etype, code, r["id"]))
            if r["is_correct"] is not None:
                kc_events.setdefault(code, []).append((r["submitted_at"], bool(r["is_correct"])))
        await conn.executemany(
            "update attempt_question_results set error_type=$1::mock_db.error_type, kc_code=$2 where id=$3", updates)

        # --- per-concept mastery (BKT + decay) ---
        now = datetime.now(tz=timezone.utc)
        scm_rows = []
        subject_mastery: dict[str, list[float]] = {}
        for code, events in kc_events.items():
            events.sort(key=lambda e: e[0])
            p = 0.35
            last_correct = None
            correct = 0
            careless = concept = wrong = 0
            for when, ok in events:
                p = analytics.bkt_posterior(p, ok)
                if ok:
                    correct += 1
                    last_correct = when
                else:
                    wrong += 1
            days_since = (now - last_correct).days if last_correct else None
            retention = analytics.decay_retention(p, days_since)
            prio = analytics.gap_priority(retention, exam_weight=1.0, recency=1.0)
            n_opp = len(events)
            careless_rate = round(min(1.0, (0.4 if wrong else 0)), 3)
            conceptual = round(min(1.0, wrong / n_opp), 3) if n_opp else 0
            scm_rows.append((uuid.uuid4(), user_id, kc_id[code], round(p, 3), n_opp, retention,
                             last_correct, None, careless_rate, conceptual, None, None, prio, True))
            # track subject-level mastery for the profile
            subj = next((s["name"] for s in subjects if code in subject_kcs.get(s["name"], [])), None)
            if subj:
                subject_mastery.setdefault(subj, []).append(retention)
        await conn.executemany(
            """insert into student_concept_mastery
               (id,user_id,kc_id,p_mastery,n_opportunities,retention_probability,last_correct_at,next_review_due,
                careless_rate,conceptual_gap_score,avg_time_z,dominant_misconception,gap_priority,is_dummy)
               values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)""", scm_rows)

        weak_subject = min(subject_mastery, key=lambda s: statistics.mean(subject_mastery[s])) if subject_mastery else "Mathematics"
        strong_subject = max(subject_mastery, key=lambda s: statistics.mean(subject_mastery[s])) if subject_mastery else "English"

        # --- per-attempt insights ---
        ai_rows = []
        n = len(attempts)
        for idx, a in enumerate(attempts):
            arows = [dict(r) for r in qrows if r["attempt_result_id"] == a["id"]]
            for ar in arows:
                ar["error_type"] = next((u[0] for u in updates if u[2] == ar["id"]), None)
            behavior = analytics.attempt_behavior(arows)
            ins = craft_attempt_insight(idx, n, float(a["accuracy_pct"] or 0), behavior, weak_subject)
            ai_rows.append((
                uuid.uuid4(), a["id"], ins["headline"], ins["goal"], ins["current_status"],
                ins["gap_diagnosis"], ins["calibration_note"], json.dumps(ins["next_actions"]),
                ins["recommended_method"], ins["behavior_archetype"], ins["pacing_note"],
                ins["negative_marking_loss"], ins["guess_rate"], ins["calibration_gap"],
                "crafted", None, True,
            ))
        await conn.executemany(
            """insert into attempt_insights
               (id,attempt_result_id,headline,goal,current_status,gap_diagnosis,calibration_note,next_actions,
                recommended_method,behavior_archetype,pacing_note,negative_marking_loss,guess_rate,calibration_gap,
                generated_by,model,is_dummy)
               values ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9,$10,$11,$12,$13,$14,$15::mock_db.insight_source,$16,$17)""",
            ai_rows)

        # --- current student profile ---
        latest_acc = float(attempts[-1]["accuracy_pct"] or 0) if attempts else 0
        weakest_kcs = sorted(scm_rows, key=lambda r: r[5] or 0)[:3]   # by retention
        strongest_kcs = sorted(scm_rows, key=lambda r: r[5] or 0, reverse=True)[:3]
        code_by_kcid = {v: k for k, v in kc_id.items()}
        name_by_code = {code: name for _, _, _, code, name, _, _ in kc_rows}
        gaps = [name_by_code[code_by_kcid[r[2]]] for r in weakest_kcs]
        strengths = [name_by_code[code_by_kcid[r[2]]] for r in strongest_kcs]
        predicted = round(min(95, latest_acc + 4), 1)
        summary = (
            f"Across {n} mocks your accuracy has climbed to about {latest_acc:.0f}%, driven mostly by "
            f"{strong_subject}. Your persistent drag is {weak_subject} — and a recurring habit of rushing the "
            f"questions you get wrong. Fix the {gaps[0] if gaps else weak_subject} gap and tighten pacing, and "
            f"you clear the next band comfortably.")
        study_plan = [
            {"step": 1, "focus": gaps[0] if gaps else weak_subject,
             "action": "Re-derive the concept, then take a 10-question retrieval quiz today and again in 3 days."},
            {"step": 2, "focus": "Careless control",
             "action": "Do one timed set with a 'read twice, then commit' rule; target <5% careless misses."},
            {"step": 3, "focus": gaps[1] if len(gaps) > 1 else "Mixed revision",
             "action": "Interleave this weak topic with a strong one so retrieval stays effortful."},
        ]
        await conn.execute(
            """insert into student_insights
               (user_id,stream_catalog_exam_code,summary,persistent_strengths,persistent_gaps,
                predicted_score,predicted_band_low,predicted_band_high,study_plan,generated_by,model,is_dummy)
               values ($1,$2,$3,$4::jsonb,$5::jsonb,$6,$7,$8,$9::jsonb,'crafted',null,true)""",
            user_id, exam_code, summary, json.dumps(strengths), json.dumps(gaps),
            predicted, round(predicted - 6, 1), round(predicted + 4, 1), json.dumps(study_plan))

        # error-type distribution for the log
        dist: dict[str, int] = {}
        for e, _, _ in updates:
            dist[e] = dist.get(e, 0) + 1
        print(f"Seeded deep insights for {email} ({exam_code}): "
              f"KCs={len(kc_rows)} mastery={len(scm_rows)} attempt_insights={len(ai_rows)} profile=1")
        print(f"  error_type distribution: {dist}")
        print(f"  weakest subject: {weak_subject}; top gaps: {gaps}")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
