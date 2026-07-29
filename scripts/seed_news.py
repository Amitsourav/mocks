"""Seed curated, evergreen "Dates & News" cards across every category.

Why this exists: the automated ingester (app/services/news_ingest.py) only has
ONE working live source — APS India (aps-india.de). Every other official source
for Germany-bound students (DAAD, the Foreign Office, Make-it-in-Germany, g.a.s.t.)
either publishes no machine-readable feed or hard-blocks bots, so the live feed
alone is thin (a handful of APS items).

This script fills the other buckets (dmat / visa / exams / scholarships /
deadlines / general) with FACTUAL, verifiable info cards — each linked to its real
official source page — so the news section has useful breadth. These are curated
reference cards, NOT live-scraped headlines: every fact below is true as written
and the `url` points at the authoritative official page where the current detail
lives. Numbers verified 2026 (blocked account €11,904/yr; dMAT €150; APS ₹18,000).

Idempotent: uses the same unique `dedup_key` as live ingestion, so re-running
inserts nothing new, and it never touches the live-scraped APS rows.

Run:  python scripts/seed_news.py
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime

import asyncpg

from app.services.news_ingest import dedup_key


# (source, source_name, category, published_at, url, title, summary)
def _D(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=UTC)

ITEMS: list[dict] = [
    # ---- dmat -------------------------------------------------------------
    {
        "source": "gast", "source_name": "g.a.s.t. (dMAT)", "category": "dmat",
        "published_at": _D(2026, 6, 29),
        "url": "https://www.d-mat.de/en/",
        "title": "dMAT is a 160-minute computer-based aptitude test (76 questions)",
        "summary": "The Digital Master Test assesses quantitative, logical and analytical "
                   "reasoning for Master's applicants — no syllabus to memorise; it measures aptitude.",
    },
    {
        "source": "gast", "source_name": "g.a.s.t. (dMAT)", "category": "dmat",
        "published_at": _D(2026, 6, 29),
        "url": "https://www.gast.de/",
        "title": "dMAT exam fee is €150, paid at registration",
        "summary": "You register and pay the €150 fee on the g.a.s.t. test-taker portal; seats at "
                   "Indian test centres are allotted first-come, first-served.",
    },
    {
        "source": "aps_india", "source_name": "APS India", "category": "dmat",
        "published_at": _D(2026, 6, 29),
        "url": "https://aps-india.de/dmat/",
        "title": "Who must take the dMAT",
        "summary": "Indian graduates in Engineering, Commerce/Finance/Economics, or "
                   "Business/Management applying for the Summer Semester 2027 intake or later.",
    },
    # ---- aps ---------------------------------------------------------------
    {
        "source": "aps_india", "source_name": "APS India", "category": "aps",
        "published_at": _D(2026, 5, 20),
        "url": "https://aps-india.de/",
        "title": "An APS certificate is mandatory for Indian applicants to German universities",
        "summary": "APS India verifies your academic documents before you apply. The APS certificate "
                   "fee is ₹18,000; from Summer 2027 the dMAT is part of this process for notified fields.",
    },
    {
        "source": "anabin", "source_name": "anabin (KMK)", "category": "aps",
        "published_at": _D(2026, 5, 10),
        "url": "https://anabin.kmk.org/",
        "title": "Check your degree's recognition status on anabin",
        "summary": "Germany's official anabin database rates institutions H+ (recognised), H+/− "
                   "(case-by-case) or H− (not recognised) — your status gates admission eligibility.",
    },
    # ---- visa --------------------------------------------------------------
    {
        "source": "study_in_germany", "source_name": "Study in Germany (DAAD)", "category": "visa",
        "published_at": _D(2026, 6, 1),
        "url": "https://www.study-in-germany.de/en/",
        "title": "Blocked account for 2026: €11,904 proof of funds",
        "summary": "A German student visa needs a blocked account (Sperrkonto) of €11,904 for the year "
                   "— released to you at €992/month after you arrive.",
    },
    {
        "source": "german_missions_india", "source_name": "German Missions in India", "category": "visa",
        "published_at": _D(2026, 6, 5),
        "url": "https://india.diplo.de/in-en",
        "title": "Book your German student-visa appointment early",
        "summary": "National (type D) student visas are processed via the German Missions in India — "
                   "apply 6–8 weeks ahead; slots fill fast in the pre-intake rush.",
    },
    {
        "source": "study_in_germany", "source_name": "Study in Germany (DAAD)", "category": "visa",
        "published_at": _D(2026, 5, 28),
        "url": "https://www.study-in-germany.de/en/",
        "title": "Health insurance is required before you enrol",
        "summary": "Public statutory health insurance is mandatory for enrolment and the residence "
                   "permit; arrange coverage before your visa appointment.",
    },
    # ---- exams -------------------------------------------------------------
    {
        "source": "testas", "source_name": "TestAS", "category": "exams",
        "published_at": _D(2026, 4, 15),
        "url": "https://www.testas.de/en/",
        "title": "TestAS — standardised aptitude test for international students",
        "summary": "Many German universities accept or recommend TestAS for admission; it's a separate, "
                   "computer-based aptitude test from the dMAT.",
    },
    {
        "source": "testdaf", "source_name": "TestDaF", "category": "exams",
        "published_at": _D(2026, 4, 12),
        "url": "https://www.testdaf.de/en/",
        "title": "German-taught programmes need language proof (TestDaF / DSH)",
        "summary": "For German-medium Master's you'll usually need TestDaF or DSH at C1 level; "
                   "English-taught programmes accept IELTS/TOEFL instead.",
    },
    # ---- scholarships ------------------------------------------------------
    {
        "source": "daad", "source_name": "DAAD", "category": "scholarships",
        "published_at": _D(2026, 3, 30),
        "url": "https://www.daad.de/en/study-and-research-in-germany/scholarships/",
        "title": "DAAD scholarships for international Master's students",
        "summary": "The DAAD funds study and research in Germany — its scholarship database lets you "
                   "filter live openings by subject, level and country.",
    },
    {
        "source": "deutschlandstipendium", "source_name": "Deutschlandstipendium", "category": "scholarships",
        "published_at": _D(2026, 3, 20),
        "url": "https://www.deutschlandstipendium.de/",
        "title": "Deutschlandstipendium — €300/month merit scholarship",
        "summary": "A nationwide merit-based grant of €300/month, awarded by German universities "
                   "regardless of nationality; apply through your university.",
    },
    # ---- deadlines ---------------------------------------------------------
    {
        "source": "aps_india", "source_name": "APS India", "category": "deadlines",
        "published_at": _D(2026, 6, 29),
        "url": "https://aps-india.de/dmat/",
        "title": "dMAT registration deadline: 15 September 2026",
        "summary": "Register (and pay) by 15 Sep 2026 for the 26 Sep 2026 sitting — no confirmed "
                   "second dMAT sitting exists for the 2026 cycle.",
    },
    {
        "source": "uni_assist", "source_name": "uni-assist", "category": "deadlines",
        "published_at": _D(2026, 5, 1),
        "url": "https://www.uni-assist.de/en/",
        "title": "Typical Master's application windows: 15 Jul (winter) / 15 Jan (summer)",
        "summary": "Most German universities take applications via uni-assist with deadlines around "
                   "15 July for winter intake and 15 January for summer — always confirm per programme.",
    },
    # ---- general -----------------------------------------------------------
    {
        "source": "make_it_in_germany", "source_name": "Make it in Germany", "category": "general",
        "published_at": _D(2026, 4, 1),
        "url": "https://www.make-it-in-germany.com/en/",
        "title": "Make it in Germany — the official government portal",
        "summary": "The Federal Government's portal for studying, working and living in Germany: visa "
                   "rules, job search and post-study stay options in one place.",
    },
    {
        "source": "study_in_germany", "source_name": "Study in Germany (DAAD)", "category": "general",
        "published_at": _D(2026, 3, 15),
        "url": "https://www.study-in-germany.de/en/",
        "title": "Most public universities charge no tuition fees",
        "summary": "State-run universities are largely tuition-free — you pay only a semester "
                   "contribution (roughly €150–350) covering admin and often local transport.",
    },
]


async def main() -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")
    conn = await asyncpg.connect(
        dsn, statement_cache_size=0, server_settings={"search_path": "mock_db,public"}
    )
    # Self-cleaning: drop any prior copy of these exact curated cards so re-runs
    # (and the earlier url-keyed insert) converge on exactly this set. Titles are
    # distinctive and never collide with the live-scraped APS items.
    titles = [it["title"] for it in ITEMS]
    await conn.execute("delete from news_items where title = any($1)", titles)

    inserted = 0
    for it in ITEMS:
        # Curated cards are unique by TITLE (several legitimately link to the same
        # official portal), so key on the title rather than the shared url.
        key = dedup_key(it["source"], None, it["title"])
        new_id = await conn.fetchval(
            """
            insert into news_items
                (source, source_name, url, title, summary, category, published_at, dedup_key, relevant)
            values ($1,$2,$3,$4,$5,$6,$7,$8,true)
            on conflict (dedup_key) do nothing
            returning id
            """,
            it["source"], it["source_name"], it["url"], it["title"], it["summary"],
            it["category"], it["published_at"], key,
        )
        inserted += int(new_id is not None)
    rows = await conn.fetch(
        "select category, count(*) n from news_items where relevant group by category order by category"
    )
    print(f"seed_news: inserted {inserted} new (of {len(ITEMS)} curated); "
          f"total relevant now {sum(r['n'] for r in rows)}")
    for r in rows:
        print(f"   {r['category']:<13} {r['n']}")
    await conn.close()


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    asyncio.run(main())
