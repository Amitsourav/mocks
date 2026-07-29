"""Link-based sharing.

A share is a FROZEN snapshot: the full report JSON is built at share time and
stored on the row, so the PUBLIC read-by-token endpoint serves that snapshot and
never touches live user data — a shared result stays "my result that day".

Security posture:
- token is crypto-random (secrets.token_urlsafe), never sequential.
- Bad / expired / revoked all return the SAME 404 (no existence probing).
- The public GET is unauthenticated, so it is IP rate-limited (best-effort Redis).
- Snapshots carry the sharer's FIRST NAME only — no email/phone/last name.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.deps import get_current_user
from app.api.routes import dashboard
from app.core.config import get_settings
from app.core.db import get_pool
from app.core.redis import get_redis
from app.schemas.social import ShareCreateIn, ShareCreateOut
from app.schemas.user import CurrentUser

router = APIRouter(tags=["share"])

SHARE_TTL_DAYS = 30
PUBLIC_RATE_LIMIT = 60        # requests per window, per IP
PUBLIC_RATE_WINDOW = 60       # seconds


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _first_name(full_name: str | None) -> str | None:
    parts = (full_name or "").strip().split()
    return parts[0] if parts else None


# --------------------------------------------------------------------------
# Snapshot builders — reuse the exact dashboard route logic. Calling a route
# function directly with an explicit `user` bypasses its `Depends`, so the
# snapshot can never drift from what the live dashboard shows.
# --------------------------------------------------------------------------

async def _build_dashboard_payload(user: CurrentUser) -> dict:
    summary = await dashboard.dashboard_summary(user=user)
    attempts = await dashboard.dashboard_attempts(user=user)
    skills = await dashboard.dashboard_skills(user=user)
    insight = await dashboard.dashboard_insight(user=user)
    concepts = await dashboard.dashboard_concepts(user=user)
    strategy = await dashboard.dashboard_strategy(user=user)
    return {
        "summary": summary.model_dump(mode="json"),
        "attempts": [a.model_dump(mode="json") for a in attempts],
        "skills": [s.model_dump(mode="json") for s in skills],
        "insight": insight.model_dump(mode="json") if insight else None,
        "concepts": [c.model_dump(mode="json") for c in concepts],
        "strategy": strategy.model_dump(mode="json"),
    }


async def _build_attempt_payload(user: CurrentUser, attempt_id: UUID) -> dict:
    # dashboard_attempt_detail raises 404 if the attempt isn't the user's.
    detail = await dashboard.dashboard_attempt_detail(attempt_id=attempt_id, user=user)
    return {"attempt": detail.model_dump(mode="json")}


@router.post("/share", response_model=ShareCreateOut, status_code=status.HTTP_201_CREATED)
async def create_share(
    payload: ShareCreateIn, user: CurrentUser = Depends(get_current_user)
) -> ShareCreateOut:
    if payload.scope not in ("dashboard", "attempt"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_scope", "message": "scope must be 'dashboard' or 'attempt'."},
        )
    if payload.scope == "attempt" and payload.attempt_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "attempt_id_required", "message": "attempt_id is required for an attempt share."},
        )

    if payload.scope == "dashboard":
        body = await _build_dashboard_payload(user)
    else:
        body = await _build_attempt_payload(user, payload.attempt_id)  # 404 if not the owner

    snapshot = {
        "scope": payload.scope,
        "shared_by": _first_name(user.full_name),  # first name only
        "generated_at": _utcnow().isoformat(),
        **body,
    }

    token = secrets.token_urlsafe(16)
    expires_at = _utcnow() + timedelta(days=SHARE_TTL_DAYS)
    await get_pool().execute(
        """
        insert into share_links (user_id, scope, attempt_id, token, payload, expires_at)
        values ($1, $2, $3, $4, $5::jsonb, $6)
        """,
        user.id, payload.scope, payload.attempt_id, token, json.dumps(snapshot), expires_at,
    )

    # The share URL points at the frontend page (which renders the public report
    # by calling GET /share/{token}); default to the configured frontend origin.
    base = (get_settings().cors_origin_list or ["http://localhost:3000"])[0].rstrip("/")
    return ShareCreateOut(token=token, url=f"{base}/share/{token}", expires_at=expires_at)


async def _rate_limit_ip(request: Request) -> None:
    """Best-effort per-IP limit for the unauthenticated read. Fails OPEN if Redis
    is unavailable — a cache outage must not take sharing down."""
    ip = request.client.host if request.client else "unknown"
    try:
        r = get_redis()
        key = f"share:rl:{ip}"
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, PUBLIC_RATE_WINDOW)
        if n > PUBLIC_RATE_LIMIT:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many requests.")
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 — Redis is best-effort; never block on it
        pass


@router.get("/share/{token}")
async def read_share(token: str, request: Request) -> dict:
    """PUBLIC — no auth. Serves the frozen snapshot. Missing / expired / revoked
    all return the same 404 so a token can't be probed for existence."""
    await _rate_limit_ip(request)
    row = await get_pool().fetchrow(
        """
        select payload from share_links
        where token = $1 and revoked_at is null
          and (expires_at is null or expires_at > now())
        """,
        token,
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    payload = row["payload"]
    return json.loads(payload) if isinstance(payload, str) else payload


@router.post("/share/{token}/revoke", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_share(token: str, user: CurrentUser = Depends(get_current_user)) -> None:
    # Owner-only. A non-owner or unknown token gets the same 404 — no probing.
    result = await get_pool().execute(
        "update share_links set revoked_at = now() where token = $1 and user_id = $2 and revoked_at is null",
        token, user.id,
    )
    if result.endswith(" 0"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
