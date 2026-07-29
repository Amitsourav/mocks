"""Auto-ingested "Dates & News" for Germany-bound students.

Pulls the dMAT schedule + official updates into `mock_db.exam_dates` /
`mock_db.news_items` so the frontend only renders. Runs on app startup and every
6 hours (see `app/main.py`), guarded by a Postgres advisory lock so multiple
uvicorn workers don't double-ingest.

Design rules (honest by construction):
  - No official API/feed exists, so the schedule is scraped from aps-india.de.
    d-mat.de is NOT used: its TLS certificate is expired, which makes automated
    fetching unreliable.
  - A source failing NEVER breaks the run — every external call is wrapped, the
    failure is logged, and the last-known-good rows keep being served.
  - The schedule scrape is all-or-nothing: if fewer than 4 dated milestones
    parse, we treat it as failed and change no dates (never partially overwrite).
  - Ingestion is idempotent — `news_items.dedup_key` (unique) makes re-runs
    insert nothing new.

The pure parse/classify helpers (`parse_schedule`, `parse_document_history`,
`diff_schedule`, `dedup_key`, `categorize`, `is_relevant`, `parse_feed`) take no
DB/network and are unit-tested against saved HTML fixtures.
"""

from __future__ import annotations

import asyncio
import hashlib
import html as html_lib
import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import httpx

from app.core.db import get_pool

logger = logging.getLogger("mock_exam")

# ---- constants -------------------------------------------------------------

APS_URL = "https://aps-india.de/dmat/"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_HTTP_TIMEOUT = 15.0

# Best-effort RSS/Atom sources. No confirmed public feed URL exists for these at
# time of writing, so each is tried and SKIPPED (logged) if unreachable/unparsed
# — the run never depends on them. Add/fix URLs here as official feeds surface.
FEEDS: list[tuple[str, str, str]] = [
    ("daad", "DAAD", "https://www.daad.de/en/rss.xml"),
    ("gast", "g.a.s.t.", "https://www.gast.de/rss.xml"),
    ("embassy_india", "German Missions in India", "https://india.diplo.de/blob/rss.xml"),
]

# Undated "mandatory in APS" milestone canonical label.
_MANDATORY_LABEL = "dMAT mandatory in APS"

# Fixed advisory-lock key so concurrent workers serialise ingestion.
_LOCK_KEY = 8264170

# Relevance filter — keep items on Germany-student themes (case-insensitive).
_RELEVANCE_KEYWORDS = (
    "aps", "visa", "student", "university", "master", "admission", "scholarship",
    "daad", "testdaf", "testas", "dmat", "blocked account", "semester", "germany",
    "study in germany", "anabin",
)

# Category by keyword priority: dmat > aps > visa > exams > scholarships > deadlines.
_CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("dmat", ("dmat", "digital master test")),
    ("aps", ("aps", "anabin", "academic evaluation")),
    ("visa", ("visa", "blocked account", "residence permit", "embassy", "consulate")),
    ("exams", ("testdaf", "testas", "ielts", "toefl", "gre", "test date", "exam")),
    ("scholarships", ("scholarship", "stipend", "funding", "grant")),
    ("deadlines", ("deadline", "last date", "apply by")),
]


# ---- typed parse results ---------------------------------------------------

@dataclass(frozen=True)
class ParsedDate:
    label: str
    date: date
    display: str


@dataclass(frozen=True)
class HistoryItem:
    published: date
    description: str


@dataclass(frozen=True)
class ScheduleChange:
    label: str
    new_date: date | None
    new_display: str


@dataclass(frozen=True)
class FeedItem:
    title: str
    url: str | None
    summary: str | None
    published: datetime


# ---- pure text helpers -----------------------------------------------------

def _clean(s: str | None) -> str:
    """Strip tags, unescape entities, collapse whitespace."""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html_lib.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_date(s: str | None) -> date | None:
    """'29 June 2026' / '29 Jun 2026' -> date, else None."""
    txt = _clean(s)
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            # A calendar date carries no timezone by design; .date() drops the
            # midnight component strptime supplies.
            return datetime.strptime(txt, fmt).date()  # noqa: DTZ007
        except ValueError:
            continue
    return None


def _display(d: date) -> str:
    """date -> '29 Jun 2026' (no leading zero on the day)."""
    return f"{d.day} {d.strftime('%b')} {d.year}"


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _as_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _canonical_label(desc: str) -> str | None:
    """Map an APS schedule description to a canonical exam_dates label."""
    d = desc.lower()
    if "deadline" in d:
        return "Registration deadline"
    if "test date" in d or ("test" in d and "date" in d):
        return "dMAT test date"
    if "certificate" in d:
        return "Certificate available"
    if "registration" in d and ("start" in d or "open" in d):
        return "Registration opens"
    return None


# ---- pure parsers (fixture-tested) -----------------------------------------

def parse_schedule(html: str) -> list[ParsedDate]:
    """Parse the 'Current schedule' <ul> into canonical dated milestones.

    Each <li> is `<strong>29 June 2026</strong> – Registration starts`. Only
    milestones that map to a canonical label AND parse a date are returned;
    the caller treats <4 as a failed scrape.
    """
    block = re.search(r"Current schedule.*?<ul>(.*?)</ul>", html, re.DOTALL | re.IGNORECASE)
    if not block:
        return []
    out: list[ParsedDate] = []
    for li in re.finditer(
        r"<li>\s*<strong>\s*(.*?)\s*</strong>\s*[–—-]\s*(.*?)\s*</li>",
        block.group(1),
        re.DOTALL,
    ):
        d = _parse_date(li.group(1))
        label = _canonical_label(_clean(li.group(2)))
        if d and label:
            out.append(ParsedDate(label=label, date=d, display=_display(d)))
    return out


def parse_summer_semester(html: str) -> int | None:
    """Parse the '(summer) semester 20XX' year for the 'mandatory in APS' milestone."""
    m = re.search(r"summer semester\s+(\d{4})", html, re.IGNORECASE)
    return int(m.group(1)) if m else None


def parse_document_history(html: str) -> list[HistoryItem]:
    """Parse the 'Document history' grid (alternating date / description cells).

    Anchors on a date-shaped cell and pairs it with the immediately following
    description cell, so trailing container `</div>`s never disturb the pairing.
    """
    start = html.find("Document history")
    if start < 0:
        return []
    grid = re.search(r"<div[^>]*display:\s*grid[^>]*>", html[start:])
    if not grid:
        return []
    inner = html[start + grid.end():]

    items: list[HistoryItem] = []
    for raw_date, raw_desc in re.findall(
        r"<div[^>]*>\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})\s*</div>\s*<div[^>]*>(.*?)</div>",
        inner,
        re.DOTALL,
    ):
        d = _parse_date(raw_date)
        desc = _clean(raw_desc)
        if d and desc:
            items.append(HistoryItem(published=d, description=desc))
    return items


def diff_schedule(parsed: list[ParsedDate], current: dict[str, date | None]) -> list[ScheduleChange]:
    """Changes vs the stored schedule: a known label whose date moved."""
    changes: list[ScheduleChange] = []
    for pd in parsed:
        if pd.label in current and current[pd.label] != pd.date:
            changes.append(ScheduleChange(label=pd.label, new_date=pd.date, new_display=pd.display))
    return changes


def schedule_change_title(change: ScheduleChange) -> str:
    return f"Schedule change: {change.label} moved to {change.new_display}"


def dedup_key(source: str, url: str | None, title: str) -> str:
    """sha256 of source + (url if present else title). Stable across runs."""
    basis = f"{source}|{url or title}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def is_relevant(title: str, summary: str | None) -> bool:
    text = f"{title} {summary or ''}".lower()
    return any(k in text for k in _RELEVANCE_KEYWORDS)


def categorize(title: str, summary: str | None) -> str:
    text = f"{title} {summary or ''}".lower()
    for cat, kws in _CATEGORY_RULES:
        if any(k in text for k in kws):
            return cat
    return "general"


def _text(el) -> str | None:
    return el.text.strip() if el is not None and el.text else None


def _parse_rss_date(s: str | None) -> datetime:
    if s:
        try:
            dt = parsedate_to_datetime(s)
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            pass
    return datetime.now(UTC)


def _parse_atom_date(s: str | None) -> datetime:
    if s:
        try:
            dt = datetime.fromisoformat(s)  # py3.12 fromisoformat parses trailing 'Z'
            return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            pass
    return datetime.now(UTC)


def parse_feed(xml_text: str) -> list[FeedItem]:
    """Minimal RSS + Atom parsing (stdlib only). Malformed feeds -> []."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    for el in root.iter():  # strip namespaces for uniform tag names
        el.tag = el.tag.rsplit("}", 1)[-1]

    items: list[FeedItem] = []
    rss_items = root.findall(".//item")
    if rss_items:
        for it in rss_items:
            title = _text(it.find("title"))
            if not title:
                continue
            items.append(FeedItem(
                title=title, url=_text(it.find("link")),
                summary=_clean(_text(it.find("description"))) or None,
                published=_parse_rss_date(_text(it.find("pubDate"))),
            ))
        return items
    for it in root.findall(".//entry"):  # Atom
        title = _text(it.find("title"))
        if not title:
            continue
        link_el = it.find("link")
        link = link_el.get("href") if link_el is not None else None
        summary = _clean(_text(it.find("summary")) or _text(it.find("content"))) or None
        items.append(FeedItem(
            title=title, url=link, summary=summary,
            published=_parse_atom_date(_text(it.find("updated")) or _text(it.find("published"))),
        ))
    return items


# ---- network + DB ----------------------------------------------------------

async def _http_get(url: str) -> str | None:
    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT, follow_redirects=True, headers={"User-Agent": _UA}
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception as exc:  # noqa: BLE001 - a failed source must never break the run
        logger.info("news_ingest: fetch failed for %s: %s", url, exc)
        return None


async def _insert_news(
    conn, *, source: str, source_name: str, url: str | None, title: str,
    summary: str | None, category: str, published_at: datetime, relevant: bool = True,
) -> bool:
    """Insert one news item; returns True if newly inserted, False on dedup hit."""
    key = dedup_key(source, url, title)
    new_id = await conn.fetchval(
        """
        insert into news_items
            (source, source_name, url, title, summary, category, published_at, dedup_key, relevant)
        values ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        on conflict (dedup_key) do nothing
        returning id
        """,
        source, source_name, url, title, summary, category, published_at, key, relevant,
    )
    return new_id is not None


async def _apply_schedule(conn, parsed: list[ParsedDate], summer_year: int | None) -> list[ScheduleChange]:
    """Update exam_dates from the parsed schedule, emitting a news_item per change."""
    rows = await conn.fetch("select label, date, display from exam_dates")
    current_date = {r["label"]: r["date"] for r in rows}
    current_display = {r["label"]: r["display"] for r in rows}

    changes = diff_schedule(parsed, current_date)
    changed_labels = {c.label for c in changes}

    for pd in parsed:
        if pd.label in changed_labels:
            await conn.execute(
                "update exam_dates set date = $2, display = $3, updated_at = now() where label = $1",
                pd.label, pd.date, pd.display,
            )
        elif pd.label not in current_date:  # a brand-new milestone the site added
            await conn.execute(
                "insert into exam_dates (label, date, display) values ($1, $2, $3) "
                "on conflict (label) do nothing",
                pd.label, pd.date, pd.display,
            )

    # Undated "mandatory in APS" milestone — tracked by display string.
    if summer_year is not None:
        disp = f"Summer {summer_year}"
        if current_display.get(_MANDATORY_LABEL) not in (None, disp):
            await conn.execute(
                "update exam_dates set display = $2, updated_at = now() where label = $1",
                _MANDATORY_LABEL, disp,
            )
            changes.append(ScheduleChange(label=_MANDATORY_LABEL, new_date=None, new_display=disp))

    for change in changes:
        title = schedule_change_title(change)
        await _insert_news(
            conn, source="aps_india", source_name="APS India", url=None,
            title=title, summary=title, category="dmat",
            published_at=datetime.now(UTC),
        )
    return changes


async def ingest_aps_india(conn) -> dict[str, int]:
    """Scrape aps-india.de: apply schedule changes + accumulate document history."""
    html = await _http_get(APS_URL)
    if not html:
        logger.warning("news_ingest: APS India page unavailable — schedule/history unchanged")
        return {"changed": 0, "inserted": 0, "skipped": 0}

    parsed = parse_schedule(html)
    changes: list[ScheduleChange] = []
    if len(parsed) >= 4:
        changes = await _apply_schedule(conn, parsed, parse_summer_semester(html))
    else:
        logger.warning(
            "news_ingest: schedule parse yielded %d milestones (<4) — leaving dates unchanged",
            len(parsed),
        )

    inserted = skipped = 0
    for hi in parse_document_history(html):
        did = await _insert_news(
            conn, source="aps_india", source_name="APS India", url=None,
            title=_truncate(hi.description, 140), summary=_truncate(hi.description, 400),
            category="aps", published_at=_as_utc(hi.published),
        )
        inserted += int(did)
        skipped += int(not did)
    return {"changed": len(changes), "inserted": inserted, "skipped": skipped}


async def ingest_feeds(conn) -> dict[str, int]:
    """Fetch each configured RSS/Atom feed; skip-safe on any failure."""
    inserted = skipped = 0
    for source, name, url in FEEDS:
        xml = await _http_get(url)
        if not xml:
            continue
        for fi in parse_feed(xml):
            summary = _truncate(fi.summary, 400) if fi.summary else None
            did = await _insert_news(
                conn, source=source, source_name=name, url=fi.url,
                title=_truncate(fi.title, 300), summary=summary,
                category=categorize(fi.title, fi.summary),
                published_at=fi.published, relevant=is_relevant(fi.title, fi.summary),
            )
            inserted += int(did)
            skipped += int(not did)
    return {"inserted": inserted, "skipped": skipped}


async def run_ingest(pool) -> None:
    """One ingestion pass, serialised across workers via a Postgres advisory lock."""
    async with pool.acquire() as conn:
        if not await conn.fetchval("select pg_try_advisory_lock($1)", _LOCK_KEY):
            logger.info("news_ingest: another worker holds the lock — skipping this run")
            return
        try:
            aps = await ingest_aps_india(conn)
            feeds = await ingest_feeds(conn)
            logger.info(
                "news_ingest: done — aps(dates_changed=%d hist_inserted=%d hist_dupes=%d) "
                "feeds(inserted=%d dupes=%d)",
                aps["changed"], aps["inserted"], aps["skipped"],
                feeds["inserted"], feeds["skipped"],
            )
        finally:
            await conn.execute("select pg_advisory_unlock($1)", _LOCK_KEY)


async def scheduler_loop(interval_seconds: int = 6 * 60 * 60) -> None:
    """Ingest immediately, then every `interval_seconds`. Errors never stop the loop."""
    while True:
        try:
            await run_ingest(get_pool())
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("news_ingest: run failed")
        await asyncio.sleep(interval_seconds)
