#!/usr/bin/env python3
"""Set daad_programs.is_public from the university public/private classification.

Source: a JSON array of {"university": str, "is_public": bool|null, ...} covering
every distinct university in daad_programs, classified against the HRK
Hochschulkompass registry (staatlich = public, privat/kirchlich = private).

Idempotent: updates is_public per university by exact name match. Reports any
university present in the DB but missing from the classification (left null).

    python scripts/seed_public_flag.py <classification.json>

Requires DATABASE_URL in the environment.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import asyncpg


async def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL not set", flush=True)
        return 2
    if len(sys.argv) < 2:
        print("usage: seed_public_flag.py <classification.json>", flush=True)
        return 2

    data = json.loads(Path(sys.argv[1]).read_text())
    by_name = {r["university"]: r.get("is_public") for r in data}

    conn = await asyncpg.connect(dsn, statement_cache_size=0)
    try:
        await conn.execute("set search_path = mock_db, public")
        db_unis = {r["university"] for r in await conn.fetch("select distinct university from daad_programs")}

        missing = sorted(db_unis - set(by_name))
        if missing:
            print(f"WARNING: {len(missing)} DB universities not in classification (is_public stays null):")
            for m in missing:
                print(f"  - {m}")

        async with conn.transaction():
            for uni, is_public in by_name.items():
                if is_public is None:
                    continue
                await conn.execute(
                    "update daad_programs set is_public = $2 where university = $1", uni, is_public
                )

        pub = await conn.fetchval("select count(*) from daad_programs where is_public is true")
        priv = await conn.fetchval("select count(*) from daad_programs where is_public is false")
        null = await conn.fetchval("select count(*) from daad_programs where is_public is null")
        pub_u = await conn.fetchval(
            "select count(distinct university) from daad_programs where is_public is true"
        )
    finally:
        await conn.close()

    print(f"programmes: public={pub} private={priv} unclassified={null}")
    print(f"public universities: {pub_u}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
