#!/usr/bin/env python3
"""Replace the dMAT Figure-Sequences bank atomically:
  1. delete every existing FIGSEQ question (cascades options / tags / solutions /
     attempt_questions),
  2. import the new content/dmat/figseq.json (questions + options + skill tags),
  3. attach each item's grounded solution from content/dmat/figseq_solutions.json
     (matched by content_hash).
All in ONE transaction — either the whole swap lands or nothing does.

Requires DATABASE_URL in the environment (same as the API / importer).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from import_questions import import_doc, content_hash  # noqa: E402

FIG = ROOT / "content" / "dmat" / "figseq.json"
META = ROOT / "content" / "dmat" / "figseq_solutions.json"


async def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    doc = json.loads(FIG.read_text())
    sols = json.loads(META.read_text())

    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        async with conn.transaction():
            exam = await conn.fetchrow("select id from mock_db.examinations where code='dMAT'")
            sec = await conn.fetchrow(
                "select id from mock_db.exam_sections where examination_id=$1 and code='FIGSEQ'",
                exam["id"])
            # 1. delete the old bank (cascades options/tags/solutions/attempt_questions)
            deleted = await conn.fetchval(
                "with d as (delete from mock_db.questions where section_id=$1 returning 1) "
                "select count(*) from d", sec["id"])
            print(f"deleted {deleted} old FIGSEQ questions")

            # 2. import the new questions + options + skill tags
            counts = await import_doc(conn, doc)
            print(f"imported: {counts}")

            # 3. attach solutions (match content_hash -> new question id)
            hash_to_qid = {
                r["content_hash"]: r["id"]
                for r in await conn.fetch(
                    "select id, content_hash from mock_db.questions where section_id=$1", sec["id"])
            }
            sol_rows = []
            missing = 0
            for s in sols:
                qid = hash_to_qid.get(s["content_hash"])
                if qid is None:
                    missing += 1
                    continue
                sol_rows.append((qid, s["solution_md"], s.get("final_answer"),
                                 s.get("correct_label")))
            await conn.executemany(
                "insert into mock_db.solutions "
                "(question_id, solution_md, final_answer, correct_label, generated_by, status) "
                "values ($1,$2,$3,$4,'code','published')",
                sol_rows)
            print(f"inserted {len(sol_rows)} solutions ({missing} unmatched)")

        # verify (outside tx)
        pub = await conn.fetchval(
            "select count(*) from mock_db.questions where section_id=$1 and status='published'", sec["id"])
        nsol = await conn.fetchval(
            "select count(*) from mock_db.solutions s join mock_db.questions q on q.id=s.question_id "
            "where q.section_id=$1", sec["id"])
        bad_opts = await conn.fetchval(
            "select count(*) from (select q.id from mock_db.questions q "
            "join mock_db.question_options o on o.question_id=q.id where q.section_id=$1 "
            "group by q.id having count(*)<>4 or count(*) filter (where o.is_correct)<>1) t", sec["id"])
        ntags = await conn.fetchval(
            "select count(*) from mock_db.question_skill_tags t "
            "join mock_db.questions q on q.id=t.question_id where q.section_id=$1", sec["id"])
        print(f"\nVERIFY  published={pub}  solutions={nsol}  skill_tags={ntags}  "
              f"bad_option_rows={bad_opts}")
    finally:
        await conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
