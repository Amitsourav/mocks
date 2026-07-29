"""Unit tests for the news-ingest pure logic (no DB, no network).

Covers the schedule parser, document-history parser, dedup-key stability, the
keyword categoriser/relevance filter, the feed parser, and the change-detection
diff — all against the saved APS fixture HTML.
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import news_ingest as ni  # noqa: E402

_FIXTURE = (Path(__file__).parent / "fixtures" / "aps_dmat.html").read_text(encoding="utf-8")


# ---- schedule parser -------------------------------------------------------

def test_parse_schedule_returns_four_canonical_milestones():
    parsed = ni.parse_schedule(_FIXTURE)
    by_label = {p.label: p for p in parsed}
    assert set(by_label) == {
        "Registration opens", "Registration deadline", "dMAT test date", "Certificate available",
    }
    assert by_label["Registration opens"].date == date(2026, 6, 29)
    assert by_label["Registration deadline"].date == date(2026, 9, 15)
    assert by_label["dMAT test date"].date == date(2026, 9, 26)
    assert by_label["Certificate available"].date == date(2026, 10, 12)
    # Human display has no leading zero on the day.
    assert by_label["dMAT test date"].display == "26 Sep 2026"


def test_parse_schedule_failed_scrape_returns_empty():
    assert ni.parse_schedule("<html><body>no schedule here</body></html>") == []


def test_parse_summer_semester():
    assert ni.parse_summer_semester(_FIXTURE) == 2027
    assert ni.parse_summer_semester("nothing dated here") is None


# ---- document-history parser -----------------------------------------------

def test_parse_document_history():
    items = ni.parse_document_history(_FIXTURE)
    assert len(items) == 3
    assert items[0].published == date(2026, 6, 29)
    assert items[0].description.startswith("Initial publication of the dMAT")
    assert items[2].published == date(2026, 7, 13)
    # Entities unescaped, tags stripped.
    assert "&#8217;" not in items[0].description
    assert "<" not in items[0].description


# ---- change detection ------------------------------------------------------

def test_diff_schedule_detects_moved_date_and_titles_it():
    # Simulate the official site moving the test date to 3 October 2026.
    moved = _FIXTURE.replace("26 September 2026", "3 October 2026")
    parsed = ni.parse_schedule(moved)
    current = {
        "Registration opens": date(2026, 6, 29),
        "Registration deadline": date(2026, 9, 15),
        "dMAT test date": date(2026, 9, 26),   # stored (old) value
        "Certificate available": date(2026, 10, 12),
    }
    changes = ni.diff_schedule(parsed, current)
    assert len(changes) == 1
    assert changes[0].label == "dMAT test date"
    assert changes[0].new_date == date(2026, 10, 3)

    title = ni.schedule_change_title(changes[0])
    assert title == "Schedule change: dMAT test date moved to 3 Oct 2026"


def test_diff_schedule_no_change_when_identical():
    parsed = ni.parse_schedule(_FIXTURE)
    current = {p.label: p.date for p in parsed}
    assert ni.diff_schedule(parsed, current) == []


# ---- dedup key -------------------------------------------------------------

def test_dedup_key_is_stable_and_url_preferred():
    k1 = ni.dedup_key("daad", "https://x/a", "Title A")
    k2 = ni.dedup_key("daad", "https://x/a", "A different title")
    # Same source+url -> same key regardless of title.
    assert k1 == k2
    # No url -> keyed on title.
    assert ni.dedup_key("aps_india", None, "Some prose") == ni.dedup_key("aps_india", None, "Some prose")
    assert ni.dedup_key("aps_india", None, "Prose one") != ni.dedup_key("aps_india", None, "Prose two")


# ---- categoriser + relevance ----------------------------------------------

def test_categorize_priority_order():
    assert ni.categorize("New dMAT test date announced", None) == "dmat"
    assert ni.categorize("APS anabin update for applicants", None) == "aps"
    assert ni.categorize("Student visa appointment slots", None) == "visa"
    assert ni.categorize("TestDaF registration open", None) == "exams"
    assert ni.categorize("DAAD scholarship for Masters", None) == "scholarships"
    assert ni.categorize("Application deadline reminder", None) == "deadlines"
    assert ni.categorize("Campus cafeteria reopens", None) == "general"
    # dmat wins over aps when both present.
    assert ni.categorize("dMAT added to APS process", None) == "dmat"


def test_is_relevant_filter():
    assert ni.is_relevant("Study in Germany: student visa guide", None)
    assert ni.is_relevant("DAAD scholarship", None)
    assert not ni.is_relevant("Local football results", None)


# ---- feed parser -----------------------------------------------------------

def test_parse_feed_rss():
    xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item>
        <title>Germany eases student visa rules</title>
        <link>https://example.org/news/1</link>
        <description>Good news for &lt;b&gt;students&lt;/b&gt;.</description>
        <pubDate>Wed, 01 Jul 2026 09:00:00 +0000</pubDate>
      </item>
    </channel></rss>"""
    items = ni.parse_feed(xml)
    assert len(items) == 1
    assert items[0].title == "Germany eases student visa rules"
    assert items[0].url == "https://example.org/news/1"
    assert items[0].published.year == 2026 and items[0].published.month == 7


def test_parse_feed_atom():
    xml = """<?xml version="1.0"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>DAAD scholarship deadline</title>
        <link href="https://example.org/a"/>
        <summary>Apply by autumn.</summary>
        <updated>2026-07-02T10:00:00Z</updated>
      </entry>
    </feed>"""
    items = ni.parse_feed(xml)
    assert len(items) == 1
    assert items[0].url == "https://example.org/a"
    assert items[0].published.month == 7


def test_parse_feed_malformed_returns_empty():
    assert ni.parse_feed("not xml at all") == []
