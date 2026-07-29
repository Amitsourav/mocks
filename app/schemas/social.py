"""Leaderboard + share (link-based) response/request models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


# ---- Leaderboard -----------------------------------------------------------

class LeaderboardEntry(BaseModel):
    rank: int
    display_name: str          # first name + last initial — never email/phone
    value: float               # the metric value (best_score)
    is_me: bool
    delta_rank: int | None = None   # rank movement vs 7 days ago (+ = climbed); null if unknown


class LeaderboardMe(BaseModel):
    rank: int | None           # null when the user has no attempts in the stream
    value: float | None
    total_participants: int
    delta_rank: int | None = None


class LeaderboardOut(BaseModel):
    scope: str                 # "stream" — ranked within the user's exam stream
    metric: str                # "best_score"
    stream_code: str | None    # the catalog_exam_code the board is scoped to
    timeframe: str             # "all" | "week"
    entries: list[LeaderboardEntry]
    around_me: list[LeaderboardEntry] | None = None   # slice around me when outside top-10
    me: LeaderboardMe


# ---- Share -----------------------------------------------------------------

class ShareCreateIn(BaseModel):
    scope: str                 # "dashboard" | "attempt"
    attempt_id: UUID | None = None


class ShareCreateOut(BaseModel):
    token: str
    url: str
    expires_at: datetime | None
