#!/usr/bin/env python3
"""Bulk question importer for mock_db.

Loads questions (Markdown + LaTeX content, options, skill tags, optional shared
stimulus) from a structured JSON file into a target exam's sections. Validates
before writing and supports a dry-run preview so authors can check the rendered
content and answer key before anything is published.

Usage:
    python scripts/import_questions.py content/dmat_pilot.json --dry-run
    python scripts/import_questions.py content/dmat_pilot.json

Requires DATABASE_URL in the environment (same value the API uses).

File format:
{
  "exam_code": "dMAT",
  "questions": [
    {
      "section_code": "MATHEQ",
      "type": "single_choice",         # single_choice|multi_select|numeric_entry|essay
      "content_md": "Solve ...",
      "position": 1,
      "marks": 1,
      "status": "published",           # draft|published|archived
      "skills": ["NUMERICAL_REASONING"],
      "stimulus_md": null,              # optional shared passage
      "numeric_answer_key": null,       # required for numeric_entry
      "options": [                      # required for choice types
        {"label": "A", "content_md": "12", "is_correct": false},
        {"label": "B", "content_md": "7",  "is_correct": true}
      ]
    }
  ]
}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import asyncpg

CHOICE_TYPES = {"single_choice", "multi_select"}
VALID_TYPES = {"single_choice", "multi_select", "numeric_entry", "essay"}
VALID_STATUS = {"draft", "published", "archived"}


class ValidationError(Exception):
    pass


def validate(doc: dict) -> list[str]:
    """Return a list of human-readable problems (empty = valid)."""
    problems: list[str] = []
    if not doc.get("exam_code"):
        problems.append("missing top-level 'exam_code'")
    questions = doc.get("questions")
    if not isinstance(questions, list) or not questions:
        problems.append("'questions' must be a non-empty list")
        return problems

    for i, q in enumerate(questions):
        tag = f"question[{i}]"
        qtype = q.get("type")
        if qtype not in VALID_TYPES:
            problems.append(f"{tag}: invalid type {qtype!r}")
        if not q.get("section_code"):
            problems.append(f"{tag}: missing section_code")
        if not q.get("content_md"):
            problems.append(f"{tag}: missing content_md")
        if q.get("status", "draft") not in VALID_STATUS:
            problems.append(f"{tag}: invalid status {q.get('status')!r}")

        if qtype in CHOICE_TYPES:
            options = q.get("options") or []
            if len(options) < 2:
                problems.append(f"{tag}: choice question needs >= 2 options")
            correct = [o for o in options if o.get("is_correct")]
            if qtype == "single_choice" and len(correct) != 1:
                problems.append(f"{tag}: single_choice needs exactly 1 correct option (got {len(correct)})")
            if qtype == "multi_select" and len(correct) < 1:
                problems.append(f"{tag}: multi_select needs >= 1 correct option")
            for j, o in enumerate(options):
                if not o.get("content_md"):
                    problems.append(f"{tag}.option[{j}]: missing content_md")
        elif qtype == "numeric_entry":
            if not q.get("numeric_answer_key"):
                problems.append(f"{tag}: numeric_entry needs numeric_answer_key")
    return problems


def preview(doc: dict) -> None:
    print(f"\n=== PREVIEW: exam {doc.get('exam_code')} — {len(doc.get('questions', []))} question(s) ===\n")
    for i, q in enumerate(doc.get("questions", [])):
        print(f"[{i}] section={q.get('section_code')} type={q.get('type')} status={q.get('status', 'draft')}")
        if q.get("stimulus_md"):
            print(f"    stimulus: {q['stimulus_md'][:80]}...")
        print(f"    Q: {q.get('content_md', '')[:120]}")
        for o in q.get("options", []):
            mark = "*" if o.get("is_correct") else " "
            print(f"      ({mark}) {o.get('label', '?')}: {o.get('content_md', '')[:60]}")
        if q.get("numeric_answer_key"):
            print(f"    key: {q['numeric_answer_key']}")
        if q.get("skills"):
            print(f"    skills: {', '.join(q['skills'])}")
        print()


async def import_doc(conn: asyncpg.Connection, doc: dict) -> dict:
    exam = await conn.fetchrow("select id from mock_db.examinations where code = $1", doc["exam_code"])
    if exam is None:
        raise ValidationError(f"exam_code {doc['exam_code']!r} not found")
    exam_id = exam["id"]

    # Resolve sections and skills up front.
    sections = {
        r["code"]: r["id"]
        for r in await conn.fetch(
            "select code, id from mock_db.exam_sections where examination_id = $1", exam_id
        )
    }
    skills = {
        r["code"]: r["id"]
        for r in await conn.fetch(
            "select code, id from mock_db.skills where examination_id = $1 or examination_id is null", exam_id
        )
    }

    counts = {"questions": 0, "options": 0, "tags": 0, "stimuli": 0}
    for q in doc["questions"]:
        section_id = sections.get(q["section_code"])
        if section_id is None:
            raise ValidationError(f"section_code {q['section_code']!r} not found for exam")

        stimulus_id = None
        if q.get("stimulus_md"):
            stimulus_id = await conn.fetchval(
                """
                insert into mock_db.stimuli (examination_id, section_id, content_md, status)
                values ($1, $2, $3, 'published') returning id
                """,
                exam_id, section_id, q["stimulus_md"],
            )
            counts["stimuli"] += 1

        question_id = await conn.fetchval(
            """
            insert into mock_db.questions
                (examination_id, section_id, stimulus_id, question_type, content_md,
                 position, marks, numeric_answer_key, status)
            values ($1,$2,$3,$4::mock_db.question_type,$5,$6,$7,$8,$9::mock_db.content_status)
            returning id
            """,
            exam_id, section_id, stimulus_id, q["type"], q["content_md"],
            q.get("position", 0), q.get("marks", 1), q.get("numeric_answer_key"),
            q.get("status", "draft"),
        )
        counts["questions"] += 1

        for pos, o in enumerate(q.get("options", []), start=1):
            await conn.execute(
                """
                insert into mock_db.question_options (question_id, label, content_md, is_correct, position)
                values ($1, $2, $3, $4, $5)
                """,
                question_id, o.get("label"), o["content_md"], bool(o.get("is_correct")), o.get("position", pos),
            )
            counts["options"] += 1

        for skill_code in q.get("skills", []):
            skill_id = skills.get(skill_code)
            if skill_id is None:
                raise ValidationError(f"skill {skill_code!r} not found for exam")
            await conn.execute(
                "insert into mock_db.question_skill_tags (question_id, skill_id) values ($1,$2) on conflict do nothing",
                question_id, skill_id,
            )
            counts["tags"] += 1
    return counts


async def main() -> int:
    parser = argparse.ArgumentParser(description="Import questions into mock_db")
    parser.add_argument("file", type=Path, help="path to the questions JSON file")
    parser.add_argument("--dry-run", action="store_true", help="validate + preview, do not write")
    args = parser.parse_args()

    doc = json.loads(args.file.read_text())

    problems = validate(doc)
    if problems:
        print("VALIDATION FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"Validation OK ({len(doc['questions'])} questions).")

    preview(doc)

    if args.dry_run:
        print("Dry run — nothing written.")
        return 0

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL not set — cannot import.", file=sys.stderr)
        return 2

    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        async with conn.transaction():
            counts = await import_doc(conn, doc)
    finally:
        await conn.close()
    print(f"Imported: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
