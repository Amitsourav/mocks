from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.core.db import get_pool
from app.core.redis import get_redis

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness(response: Response) -> dict:
    """Deep check: Postgres and Redis both reachable.

    The status code is what load balancers act on, so it must reflect whether
    this instance can actually serve traffic:
      - Postgres unreachable -> 503; every endpoint would fail.
      - Redis unreachable    -> 200 "degraded"; the cache is best-effort and the
        app serves correctly without it, so pulling the pod would cause an
        outage rather than prevent one.
    """
    checks: dict[str, str] = {}
    try:
        await get_pool().fetchval("select 1;")
        checks["postgres"] = "ok"
    except Exception as exc:  # noqa: BLE001 - report, don't crash the probe
        checks["postgres"] = f"error: {exc}"
    try:
        await get_redis().ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["redis"] = f"error: {exc}"

    if checks["postgres"] != "ok":
        checks["status"] = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif checks["redis"] != "ok":
        checks["status"] = "degraded"
    else:
        checks["status"] = "ok"
    return checks
