#!/usr/bin/env python3
"""Load the Anabin Indian-institution dataset into mock_db.anabin_institutions.

Source: content/anabin/india.json — 1,307 institutions extracted from Germany's
official Anabin database (anabin.kmk.org), each with H+/H+/-/H- recognition
status, aliases, city/state and institution type.

Idempotent: truncates and reloads (the table is a reference snapshot, not
user data). Requires DATABASE_URL in the environment (same value the API uses).

    python scripts/seed_anabin.py
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import asyncpg

DATA = Path(__file__).resolve().parents[1] / "content" / "anabin" / "india.json"
VALID_STATUS = {"H+", "H+/-", "H-"}


async def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL not set", flush=True)
        return 2

    rows = json.loads(DATA.read_text())
    # Guard against a malformed pull silently wiping the table.
    bad = [r for r in rows if not r.get("name") or r.get("status") not in VALID_STATUS]
    if bad:
        print(f"Refusing to seed: {len(bad)} rows have no name or an unexpected status.", flush=True)
        return 1

    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        async with conn.transaction():
            await conn.execute("set search_path = mock_db, public")
            # Detach any user selections first (FK), then reload the reference set.
            # DELETE (not TRUNCATE): Postgres refuses to TRUNCATE a table that is
            # referenced by a FK, even when no rows actually point to it.
            await conn.execute("update users set anabin_institution_id = null")
            await conn.execute("delete from anabin_institutions")
            await conn.executemany(
                """
                insert into anabin_institutions
                    (name, aliases, city, state, institution_type, status)
                values ($1, $2, $3, $4, $5, $6)
                """,
                [
                    (r["name"], r.get("aliases") or [], r.get("city"), r.get("state"),
                     r.get("institution_type"), r["status"])
                    for r in rows
                ],
            )
        counts = await conn.fetch(
            "select status, count(*) as n from anabin_institutions group by status order by n desc"
        )
    finally:
        await conn.close()

    print(f"Seeded {len(rows)} institutions.")
    for c in counts:
        print(f"  {c['status']:6} {c['n']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
