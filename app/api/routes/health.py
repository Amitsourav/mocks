from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.core.config import get_settings
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

    # Informational only (no secret exposed): whether THIS process can read the
    # CRM env vars. Does not affect readiness status. Diagnoses "leads not sending
    # because the running process can't see CRM_API_URL / CRM_WEBSITE_LEAD_SECRET".
    _s = get_settings()
    checks["crm"] = "configured" if (_s.crm_api_url and _s.crm_website_lead_secret) else "unconfigured"

    if checks["postgres"] != "ok":
        checks["status"] = "unavailable"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif checks["redis"] != "ok":
        checks["status"] = "degraded"
    else:
        checks["status"] = "ok"
    return checks
