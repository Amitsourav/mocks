from __future__ import annotations

from fastapi import APIRouter

from app.core.db import get_pool
from app.core.redis import get_redis

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness() -> dict:
    """Deep check: Postgres and Redis both reachable."""
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
    checks["status"] = "ok" if all(v == "ok" for k, v in checks.items() if k != "status") else "degraded"
    return checks
