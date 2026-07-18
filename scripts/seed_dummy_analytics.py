#!/usr/bin/env python3
"""Generate a rich DUMMY analytics history for a demo account.

Creates ~10 completed mock attempts (with per-section, per-skill, per-question
breakdowns and an improving trend over time) tied to the user's REAL current
stream, so the dashboard and mock-test listing stay consistent. Every row is
flagged is_dummy=true so it is trivially purgeable when the live scoring pipeline
lands.

Deterministic (fixed RNG seed) so re-runs reproduce the same demo. Idempotent:
deletes the target user's dummy attempt_results (children cascade) first.

Run:  .venv/bin/python scripts/seed_dummy_analytics.py [email]
"""

from __future__ import annotations

import asyncio
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EMAIL = "prsuman25@gmail.com"
N_ATTEMPTS = 10
Q_PER_ATTEMPT = 40
RNG = random.Random(4207)


def get_dsn() -> str | None:
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        return dsn
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    return None


async def main() -> int:
    email = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EMAIL
    dsn = get_dsn()
    if not dsn:
        print("DATABASE_URL not set")
        return 2

    conn = await asyncpg.connect(dsn, statement_cache_size=0, server_settings={"search_path": "mock_db,public"})
    try:
        user = await conn.fetchrow("select id, full_name from users where email = $1", email)
        if user is None:
            print(f"No user with email {email}")
            return 1
        user_id = user["id"]

        stream = await conn.fetchrow(
            "select catalog_exam_code from user_stream_selections where user_id = $1 order by created_at desc limit 1",
            user_id,
        )
        if stream is None:
            print(f"{email} has no stream selection")
            return 1
        exam_code = stream["catalog_exam_code"]
        exam = await conn.fetchrow("select id, name from catalog_exams where code = $1", exam_code)
        exam_id = exam["id"]

        # Sections = the exam's subjects; skills = a sample of the exam's skills.
        subjects = [r["name"] for r in await conn.fetch(
            "select name from syllabus_subjects where catalog_exam_id = $1 order by position", exam_id)]
        if not subjects:
            subjects = ["Section 1", "Section 2", "Section 3"]
        skill_rows = await conn.fetch(
            "select code, name from skills where catalog_exam_id = $1 order by random() limit 10", exam_id)
        skills = [(r["code"], r["name"]) for r in skill_rows] or [(None, "General")]

        # Candidate mocks to attribute attempts to (prefer full/subject scope).
        mock_ids = [r["id"] for r in await conn.fetch(
            "select id from mock_tests where catalog_exam_id = $1 and scope in ('full','subject') order by position limit 20",
            exam_id)]

        print(f"Demo: {email} ({user['full_name']}) stream={exam_code} ({exam['name']}); "
              f"{len(subjects)} sections, {len(skills)} skills, {len(mock_ids)} candidate mocks")

        # --- Clear existing dummy data for this user ---
        await conn.execute("delete from attempt_results where user_id = $1 and is_dummy = true", user_id)

        now = datetime.now(tz=timezone.utc)
        ar_rows, sec_rows, skl_rows, q_rows = [], [], [], []

        for i in range(N_ATTEMPTS):
            ar_id = uuid.uuid4()
            # improving trend: accuracy 0.52 -> 0.86 across attempts, with noise
            base = 0.52 + (0.34 * i / (N_ATTEMPTS - 1))
            acc = min(0.95, max(0.35, base + RNG.uniform(-0.05, 0.05)))
            total = Q_PER_ATTEMPT
            attempted = RNG.randint(int(total * 0.85), total)
            correct = round(attempted * acc)
            wrong = attempted - correct
            skipped = total - attempted
            max_score = float(total)
            score = round(correct - 0.25 * wrong, 2)  # illustrative +1/-0.25
            percentile = round(min(99.5, 40 + base * 60 + RNG.uniform(-3, 3)), 2)
            accuracy_pct = round(100 * correct / attempted, 2) if attempted else 0
            days_ago = (N_ATTEMPTS - i) * 6 + RNG.randint(0, 3)
            started = now - timedelta(days=days_ago, minutes=RNG.randint(0, 300))
            dur = RNG.randint(1800, 5400)
            submitted = started + timedelta(seconds=dur)
            mock_id = RNG.choice(mock_ids) if mock_ids else None

            ar_rows.append((ar_id, user_id, mock_id, exam_code, started, submitted, dur,
                            total, attempted, correct, wrong, skipped, score, max_score,
                            percentile, accuracy_pct, True))

            # per-section
            per_sec = total // len(subjects)
            for pos, sec in enumerate(subjects):
                s_tot = per_sec
                s_acc = min(0.97, max(0.3, acc + RNG.uniform(-0.15, 0.15)))
                s_att = RNG.randint(int(s_tot * 0.85), s_tot)
                s_cor = round(s_att * s_acc)
                sec_rows.append((uuid.uuid4(), ar_id, sec, s_tot, s_cor, s_att - s_cor,
                                 s_tot - s_att, round(s_cor - 0.25 * (s_att - s_cor), 2),
                                 round(100 * s_cor / s_att, 2) if s_att else 0,
                                 RNG.randint(35000, 95000), pos))

            # per-skill
            for code, name in skills:
                sk_tot = RNG.randint(3, 8)
                sk_acc = min(0.98, max(0.25, acc + RNG.uniform(-0.2, 0.2)))
                sk_cor = round(sk_tot * sk_acc)
                skl_rows.append((uuid.uuid4(), ar_id, code, name, sk_tot, sk_cor,
                                 round(100 * sk_cor / sk_tot, 2), RNG.randint(30000, 110000)))

            # per-question
            for qn in range(1, total + 1):
                sec = subjects[(qn - 1) % len(subjects)]
                code = skills[(qn - 1) % len(skills)][0]
                if qn > attempted:
                    is_correct = None  # skipped
                else:
                    is_correct = RNG.random() < acc
                q_rows.append((uuid.uuid4(), ar_id, qn, sec, code, is_correct,
                               RNG.randint(15000, 180000),
                               RNG.choice(["easy", "medium", "hard"]),
                               RNG.random() < 0.12))

        async with conn.transaction():
            await conn.executemany(
                """insert into attempt_results
                   (id,user_id,mock_test_id,catalog_exam_code,started_at,submitted_at,duration_seconds,
                    total_questions,attempted,correct,wrong,skipped,score,max_score,percentile,accuracy_pct,is_dummy)
                   values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)""", ar_rows)
            await conn.executemany(
                """insert into attempt_section_results
                   (id,attempt_result_id,section_name,total,correct,wrong,skipped,score,accuracy_pct,avg_time_ms,position)
                   values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)""", sec_rows)
            await conn.executemany(
                """insert into attempt_skill_results
                   (id,attempt_result_id,skill_code,skill_name,total,correct,accuracy_pct,avg_time_ms)
                   values ($1,$2,$3,$4,$5,$6,$7,$8)""", skl_rows)
            await conn.executemany(
                """insert into attempt_question_results
                   (id,attempt_result_id,question_no,section_name,skill_code,is_correct,time_spent_ms,difficulty,marked_for_review)
                   values ($1,$2,$3,$4,$5,$6,$7,$8,$9)""", q_rows)

        print(f"Seeded dummy: attempts={len(ar_rows)} sections={len(sec_rows)} "
              f"skills={len(skl_rows)} questions={len(q_rows)}")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
