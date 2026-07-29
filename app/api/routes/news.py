"""Read-only "Dates & News" endpoints.

Both require a valid session (`get_current_user`), like the dashboard routes.
Data is written by the background ingester (`app/services/news_ingest.py`); these
just serve the last-known-good rows — so an ingestion outage never affects reads.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.db import get_pool
from app.schemas.news import ExamDateOut, ExamDatesOut, NewsItemOut, NewsListOut
from app.schemas.user import CurrentUser

router = APIRouter(prefix="/news", tags=["news"])


@router.get("", response_model=NewsListOut)
async def list_news(
    category: str | None = None,
    limit: int = 30,
    _: CurrentUser = Depends(get_current_user),
) -> NewsListOut:
    """Relevant news, newest first. Optional `category` filter; limit 1–100 (default 30)."""
    lim = min(max(limit, 1), 100)
    where = ["relevant = true"]
    args: list = []
    if category:
        args.append(category)
        where.append(f"category = ${len(args)}")
    args.append(lim)
    rows = await get_pool().fetch(
        f"""
        select id, source_name, url, title, summary, category, published_at
        from news_items
        where {' and '.join(where)}
        order by published_at desc
        limit ${len(args)}
        """,
        *args,
    )
    return NewsListOut(items=[NewsItemOut(**dict(r)) for r in rows])


@router.get("/dates", response_model=ExamDatesOut)
async def list_dates(_: CurrentUser = Depends(get_current_user)) -> ExamDatesOut:
    """The dMAT schedule, chronological with undated ('Summer 2027') milestones last."""
    rows = await get_pool().fetch(
        "select label, date, display from exam_dates order by date asc nulls last"
    )
    return ExamDatesOut(items=[ExamDateOut(**dict(r)) for r in rows])
