"""Response models for the auto-ingested "Dates & News" feed.

`ExamDateOut` mirrors the frontend's existing shape in `lib/important-dates.ts`
(label / ISO yyyy-mm-dd date / human display), so the page can swap its seeded
fallback for the live endpoint with no shape change. The date type is imported
as `date_type` so the field can be named `date` (matching that shape) without the
field name shadowing the type in the class namespace.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class NewsItemOut(BaseModel):
    id: UUID
    source_name: str
    url: str | None = None
    title: str
    summary: str | None = None
    category: str
    published_at: datetime


class NewsListOut(BaseModel):
    items: list[NewsItemOut]


class ExamDateOut(BaseModel):
    label: str
    date: date_type | None = None   # ISO yyyy-mm-dd; null for undated milestones
    display: str                    # human form: '15 Sep 2026', 'Summer 2027'


class ExamDatesOut(BaseModel):
    items: list[ExamDateOut]
