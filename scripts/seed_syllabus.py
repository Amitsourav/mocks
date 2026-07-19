#!/usr/bin/env python3
"""Seed the real syllabus catalog into mock_db from docs/syllabus/*.json.

Populates exam_variants, syllabus_subjects, syllabus_chapters, catalog-scoped
skills, and mock_tests (full / subject / chapter, incl. govt category-shared
sectionals). Uses client-generated UUIDs + bulk executemany for speed.

Idempotent: clears the catalog rows it owns (preserving dMAT engine skills, which
have examination_id set) and re-inserts. Requires DATABASE_URL (falls back to .env).

Run:  .venv/bin/python scripts/seed_syllabus.py
"""

from __future__ import annotations

import asyncio
import glob
import json
import os
import uuid
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
SYLLABUS_DIR = ROOT / "docs" / "syllabus"


def get_dsn() -> str | None:
    dsn = os.environ.get("DATABASE_URL")
    if dsn:
        return dsn
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip()
    return None


async def main() -> int:
    dsn = get_dsn()
    if not dsn:
        print("DATABASE_URL not set")
        return 2

    docs = [json.load(open(f)) for f in sorted(glob.glob(str(SYLLABUS_DIR / "*.json")))]

    variants: list[tuple] = []   # (id, catalog_exam_id, code, name, position)
    subjects: list[tuple] = []   # (id, category_id, catalog_exam_id, code, name, position)
    chapters: list[tuple] = []   # (id, subject_id, code, name, position)
    skills: list[tuple] = []     # (code, name, catalog_exam_id, subject_id)
    mocks: list[tuple] = []      # built after refs resolved

    variant_id: dict[str, str] = {}
    subject_id: dict[str, str] = {}
    chapter_id: dict[str, str] = {}

    conn = await asyncpg.connect(
        dsn, statement_cache_size=0, server_settings={"search_path": "mock_db,public"}
    )
    try:
        cat = {r["code"]: r["id"] for r in await conn.fetch("select code, id from mock_categories")}
        exams = {
            r["code"]: (r["id"], r["category_id"])
            for r in await conn.fetch("select code, id, category_id from catalog_exams")
        }
        dmat_exam = await conn.fetchval("select id from examinations where code = 'dMAT'")
        dmat_exam_id = exams.get("DMAT", (None,))[0]

        def add_subject(code, name, position, *, category_id=None, catalog_exam_id=None):
            sid = uuid.uuid4()
            subject_id[code] = sid
            subjects.append((sid, category_id, catalog_exam_id, code, name, position))
            return sid

        def add_chapters(sid, chs):
            for i, ch in enumerate(chs or [], start=1):
                cid = uuid.uuid4()
                chapter_id[ch["code"]] = cid
                chapters.append((cid, sid, ch["code"], ch["name"], i))

        def add_skills(sks, sid, exam_id):
            for sk in sks or []:
                skills.append((sk["code"], sk["name"], exam_id, sid))

        # Pass 1 — collect variants/subjects/chapters/skills
        for doc in docs:
            for ss in doc.get("category_shared_subjects", []):
                sid = add_subject(ss["code"], ss["name"], 0, category_id=cat.get(ss["category_code"]))
                add_chapters(sid, ss.get("chapters"))
                add_skills(ss.get("skills"), sid, None)
            for exam in doc.get("exams", []):
                ec = exam["catalog_exam_code"]
                if ec not in exams:
                    print(f"  WARN unknown catalog_exam_code {ec}")
                    continue
                exam_id, _ = exams[ec]
                for i, v in enumerate(exam.get("variants", []), start=1):
                    vid = uuid.uuid4()
                    variant_id[v["code"]] = vid
                    variants.append((vid, exam_id, v["code"], v["name"], i))
                for j, subj in enumerate(exam.get("subjects", []), start=1):
                    sid = add_subject(subj["code"], subj["name"], j, catalog_exam_id=exam_id)
                    add_chapters(sid, subj.get("chapters"))
                    add_skills(subj.get("skills"), sid, exam_id)

        # Pass 2 — mock_tests (refs resolvable)
        def add_mock(m, *, category_id=None, catalog_exam_id=None, default_variant=None):
            scope = m["scope"]
            s_id = subject_id.get(m.get("subject_code")) if m.get("subject_code") else None
            c_id = chapter_id.get(m.get("chapter_code")) if m.get("chapter_code") else None
            v_id = variant_id.get(m.get("variant_code")) if m.get("variant_code") else default_variant
            if scope == "subject" and s_id is None:
                print(f"  WARN subject mock missing ref: {m.get('title')}")
            if scope == "chapter" and c_id is None:
                print(f"  WARN chapter mock missing ref: {m.get('title')}")
            linked = dmat_exam if (catalog_exam_id == dmat_exam_id and scope == "full") else None
            dur = (m.get("duration_min") or 0) * 60 or None
            mocks.append((
                scope, category_id, catalog_exam_id, v_id, s_id, c_id,
                m["title"], m.get("description"), dur, m.get("questions"),
                m.get("difficulty"), m.get("position", 0), linked,
            ))

        for doc in docs:
            for m in doc.get("category_shared_mocks", []):
                add_mock(m, category_id=cat.get("JOB"))
            for exam in doc.get("exams", []):
                ec = exam["catalog_exam_code"]
                if ec not in exams:
                    continue
                exam_id, category_id = exams[ec]
                dv = variant_id.get(exam["variants"][0]["code"]) if exam.get("variants") else None
                for m in exam.get("mocks", []):
                    add_mock(m, category_id=category_id, catalog_exam_id=exam_id, default_variant=dv)

        # --- Write: clear + bulk insert, all in one transaction ---
        async with conn.transaction():
            await conn.execute("delete from mock_tests")
            await conn.execute("delete from skills where catalog_exam_id is not null or subject_id is not null")
            await conn.execute("delete from syllabus_chapters")
            await conn.execute("delete from syllabus_subjects")
            await conn.execute("delete from exam_variants")

            await conn.executemany(
                "insert into exam_variants (id, catalog_exam_id, code, name, position) values ($1,$2,$3,$4,$5)",
                variants,
            )
            await conn.executemany(
                "insert into syllabus_subjects (id, category_id, catalog_exam_id, code, name, position) values ($1,$2,$3,$4,$5,$6)",
                subjects,
            )
            await conn.executemany(
                "insert into syllabus_chapters (id, subject_id, code, name, position) values ($1,$2,$3,$4,$5)",
                chapters,
            )
            await conn.executemany(
                "insert into skills (code, name, catalog_exam_id, subject_id) values ($1,$2,$3,$4)",
                skills,
            )
            await conn.executemany(
                """insert into mock_tests
                   (scope, category_id, catalog_exam_id, variant_id, subject_id, chapter_id,
                    title, description, duration_seconds, total_questions, difficulty, position, linked_examination_id)
                   values ($1::mock_scope,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)""",
                mocks,
            )

        print(f"Seeded: variants={len(variants)} subjects={len(subjects)} "
              f"chapters={len(chapters)} skills={len(skills)} mocks={len(mocks)}")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
