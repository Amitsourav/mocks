"""Populate daad_programs.admission_mode from authoritative HRK data.

Source: the German Rectors' Conference "Hochschulkompass" (HRK) — the official
registry that carries each programme's Zulassungsmodus — served via DAAD's public
HSK API (api.daad.de/api/ajax/hsk/list). This is the authoritative source named in
migration 0019; the DAAD International Programmes feed that seeded daad_programs
does NOT carry the flag, so we cross-reference here.

HSK admission codes -> our admission_mode:
    O            Without admission restriction              -> 'open'
    A, E, X      Nationwide / selection / local restriction -> 'restricted'
    XX           No admission of first-year students        -> (skipped, left null)

Matching is PRECISION-FIRST and honest by construction: we only set a mode when a
programme confidently matches an HSK Master entry at the same university (shared
distinctive university token + high name similarity). Everything else stays null
("unknown") — a wrong 'open'/'restricted' label misleads applicants far worse than
an honest null does. Coverage + sample matches are logged so match quality can be
eyeballed.

Two-phase + cached so it survives DAAD's rate-limit and a killed process:
  - FETCH pulls HSK Master data (few big requests) and checkpoints each admission
    sweep to a local JSON cache. api.daad.de rate-limits bursts with a 403; the
    cache means a killed/blocked run resumes instead of restarting.
  - APPLY matches the cached data to daad_programs and writes admission_mode with
    NO network — so once the fetch lands even once, finishing can never re-block.

Usage:
    python scripts/seed_admission_mode.py            # fetch-if-needed, then apply
    python scripts/seed_admission_mode.py fetch      # only fetch to cache
    python scripts/seed_admission_mode.py apply       # only apply cached data to DB
    python scripts/seed_admission_mode.py --refetch  # ignore cache, fetch fresh

Idempotent: resets public rows' admission_mode to null, then repopulates.
"""

from __future__ import annotations

import asyncio
import difflib
import json
import os
import re
import sys
import tempfile
import unicodedata
from pathlib import Path

import asyncpg
import httpx

HSK_URL = "https://api.daad.de/api/ajax/hsk/list/en"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
MASTER_DEGREE = "37"
MODE_BY_CODE = {"O": "open", "A": "restricted", "E": "restricted", "X": "restricted"}
PAGE_SIZE = 500  # bigger pages -> ~20 requests instead of ~105, less likely to re-block
CACHE_PATH = Path(tempfile.gettempdir()) / "hsk_master_admission.json"

NAME_THRESHOLD = 0.82   # min name similarity to accept a match
UNI_THRESHOLD = 0.55    # min full-university similarity to accept a match

_UNI_STOP = {
    "university", "universities", "universitaet", "universitat", "of", "applied",
    "sciences", "science", "the", "for", "and", "technology", "technical",
    "hochschule", "fachhochschule", "college", "school", "institute",
}
_NAME_STOP = {
    "master", "masters", "science", "arts", "engineering", "of", "in", "and",
    "the", "for", "msc", "ma", "meng", "mba", "m", "sc", "eng", "a", "an",
    "international", "programme", "program", "study", "studies", "degree",
}
_CITY_ALIAS = {
    "munich": "munchen", "cologne": "koln", "nuremberg": "nurnberg",
    "brunswick": "braunschweig", "hanover": "hannover", "vienna": "wien",
}


# ---- normalization + matching (pure) ---------------------------------------

def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _tokens(s: str) -> list[str]:
    s = _strip_accents(s or "").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return [_CITY_ALIAS.get(t, t) for t in s.split() if t]


def _uni_core(s: str) -> set[str]:
    return {t for t in _tokens(s) if t not in _UNI_STOP}


def _name_key(s: str) -> str:
    return " ".join(sorted(t for t in _tokens(s) if t not in _NAME_STOP))


def _uni_key(s: str) -> str:
    return " ".join(sorted(_tokens(s)))


def _ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def build_index(entries: list[dict]) -> dict[str, list[dict]]:
    """Block HSK entries by each distinctive university token for fast lookup."""
    idx: dict[str, list[dict]] = {}
    for e in entries:
        e["_ukey"] = _uni_key(e["uni"])
        e["_nkey"] = _name_key(e["name"])
        for tok in _uni_core(e["uni"]):
            idx.setdefault(tok, []).append(e)
    return idx


def match(prog: dict, idx: dict[str, list[dict]]) -> tuple[dict | None, float]:
    """Best confident HSK match for one of our programmes, else (None, best_ratio)."""
    ukey = _uni_key(prog["university"])
    nkey = _name_key(prog["name"])
    seen: set[int] = set()
    best, best_r = None, 0.0
    for tok in _uni_core(prog["university"]):
        for e in idx.get(tok, []):
            if id(e) in seen:
                continue
            seen.add(id(e))
            if _ratio(ukey, e["_ukey"]) < UNI_THRESHOLD:
                continue
            r = _ratio(nkey, e["_nkey"])
            if r > best_r:
                best, best_r = e, r
    return (best, best_r) if (best and best_r >= NAME_THRESHOLD) else (None, best_r)


# ---- fetch phase (network, cached + checkpointed) --------------------------

def _load_cache() -> dict[str, list[dict]]:
    if CACHE_PATH.exists():
        try:
            return json.loads(CACHE_PATH.read_text())
        except (ValueError, OSError):
            pass
    return {}


def _save_cache(cache: dict) -> None:
    CACHE_PATH.write_text(json.dumps(cache))


async def _get_results(client: httpx.AsyncClient, params: dict) -> dict:
    """GET the HSK list; back off long enough to outlast DAAD's 403 rate block."""
    backoffs = [10, 20, 30, 60, 120, 180, 300, 300, 300, 300]
    last = ""
    for wait in backoffs:
        try:
            r = await client.get(HSK_URL, params=params)
            if "json" in r.headers.get("content-type", "") and r.text.strip():
                return r.json()["results"]
            last = f"status={r.status_code} ct={r.headers.get('content-type','')} len={len(r.text)}"
        except (httpx.HTTPError, ValueError) as exc:
            last = f"{type(exc).__name__}: {exc}"
        await asyncio.sleep(wait)
    raise RuntimeError(f"HSK list failed after retries ({last}): {params}")


async def _fetch_code(client: httpx.AsyncClient, code: str, mode: str) -> list[dict]:
    entries: list[dict] = []
    offset, guard = 0, 0
    while True:
        guard += 1
        if guard > 1000:  # runaway backstop
            break
        res = await _get_results(client, {
            "hec-degreeType": MASTER_DEGREE, "hec-admissionMode": code,
            "hec-limit": PAGE_SIZE, "hec-offset": offset,
        })
        count, items = res["count"], res["items"]
        for it in items:
            entries.append({
                "uni": it.get("subline", ""), "name": it.get("headline", ""),
                "hec": it.get("id", ""), "mode": mode,
            })
        offset += len(items)
        if not items or offset >= count:
            break
        await asyncio.sleep(0.5)
    return entries


async def phase_fetch(refetch: bool = False) -> list[dict]:
    """Fetch HSK Master entries per admission code, checkpointing each to cache."""
    cache = {} if refetch else _load_cache()
    headers = {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.daad.de/en/studying-in-germany/universities/all-degree-programmes/",
        "X-Requested-With": "XMLHttpRequest",
    }
    async with httpx.AsyncClient(timeout=60, follow_redirects=True, headers=headers) as client:
        for code, mode in MODE_BY_CODE.items():
            if cache.get(code):
                print(f"  cached {code} ({mode}): {len(cache[code])}")
                continue
            cache[code] = await _fetch_code(client, code, mode)
            _save_cache(cache)  # checkpoint after each sweep — resumable if killed
            print(f"  fetched {code} ({mode}): {len(cache[code])}")
    entries = [e for v in cache.values() for e in v]
    print(f"  total HSK Master entries cached: {len(entries)}  ({CACHE_PATH})")
    return entries


# ---- apply phase (offline: match + write DB) -------------------------------

async def phase_apply(entries: list[dict]) -> None:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL not set")
    idx = build_index(entries)
    conn = await asyncpg.connect(dsn, statement_cache_size=0,
                                 server_settings={"search_path": "mock_db,public"})
    progs = await conn.fetch(
        "select id, name, university, city from daad_programs where is_public is true"
    )
    print(f"Matching {len(progs)} public programmes against {len(entries)} HSK entries…")

    updates: list[tuple] = []
    samples: list[str] = []
    for p in progs:
        m, r = match(dict(p), idx)
        if m:
            updates.append((m["mode"], p["id"]))
            if len(samples) < 15:
                samples.append(f"  [{m['mode']:<10}] {p['name'][:42]:<42} ~ HSK: {m['name'][:40]} ({r:.2f})")

    await conn.execute("update daad_programs set admission_mode = null where is_public is true")
    await conn.executemany(
        "update daad_programs set admission_mode = $1, updated_at = now() where id = $2", updates
    )

    print("\nSample matches (eyeball precision):")
    print("\n".join(samples))
    dist = await conn.fetch(
        """select coalesce(admission_mode,'(null/unknown)') m, count(*) n
           from daad_programs where is_public is true group by admission_mode order by n desc"""
    )
    print(f"\nMatched {len(updates)} / {len(progs)} public programmes. Distribution:")
    for d in dist:
        print(f"   {d['m']:<18} {d['n']}")
    await conn.close()


async def main() -> None:
    arg = next((a for a in sys.argv[1:] if not a.startswith("-")), "all")
    refetch = "--refetch" in sys.argv

    if arg == "apply":
        entries = [e for v in _load_cache().values() for e in v]
        if not entries:
            raise SystemExit(f"No cached HSK data at {CACHE_PATH} — run 'fetch' first.")
        print(f"Using cached HSK data: {len(entries)} entries")
        await phase_apply(entries)
        return

    print("Fetching HSK Master admission modes (authoritative HRK data)…")
    entries = await phase_fetch(refetch=refetch)
    if arg == "fetch":
        print("Fetch complete — cached. Run 'apply' to write to the DB.")
        return
    await phase_apply(entries)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    asyncio.run(main())
