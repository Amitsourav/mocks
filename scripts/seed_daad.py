#!/usr/bin/env python3
"""Load the DAAD Master's-programmes dataset into mock_db.daad_programs.

Source: content/daad/masters.json — 1,716 English/international Master's
programmes at German universities, from the official DAAD International
Programmes database (daad.de).

Idempotent: truncate + reload (reference snapshot, not user data). Requires
DATABASE_URL in the environment.

    python scripts/seed_daad.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import asyncpg

DATA = Path(__file__).resolve().parents[1] / "content" / "daad" / "masters.json"


async def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL not set", flush=True)
        return 2

    rows = json.loads(DATA.read_text())
    bad = [r for r in rows if not r.get("name") or not r.get("university")]
    if bad:
        print(f"Refusing to seed: {len(bad)} rows missing name/university.", flush=True)
        return 1

    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        async with conn.transaction():
            await conn.execute("set search_path = mock_db, public")
            await conn.execute("truncate daad_programs")
            await conn.executemany(
                """
                insert into daad_programs
                    (daad_id, name, university, city, languages, subject,
                     tuition, duration, application_deadline, link)
                values ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                """,
                [
                    (r.get("daad_id"), r["name"], r["university"], r.get("city"),
                     r.get("languages") or [], r.get("subject"), r.get("tuition"),
                     r.get("duration"), r.get("application_deadline"), r.get("link"))
                    for r in rows
                ],
            )
        n = await conn.fetchval("select count(*) from daad_programs")
        unis = await conn.fetchval("select count(distinct university) from daad_programs")
    finally:
        await conn.close()

    print(f"Seeded {n} programmes across {unis} universities.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
