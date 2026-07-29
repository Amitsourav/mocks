from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    attempts,
    dashboard,
    exams,
    health,
    me,
    mock_tests,
    news,
    reference,
    share,
)
from app.core import db, redis
from app.core.config import get_settings
from app.services import news_ingest

settings = get_settings()
logging.basicConfig(level=settings.log_level.upper())
logger = logging.getLogger("mock_exam")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    logger.info("Postgres pool ready")
    try:
        await redis.connect()
        logger.info("Redis ready")
    except Exception as exc:  # noqa: BLE001 - Redis optional at boot in dev
        logger.warning("Redis unavailable at startup: %s", exc)
    # Ingest "Dates & News" now (non-blocking) and every 6h thereafter. The task
    # is fire-and-forget; the advisory lock inside keeps multiple workers safe.
    news_task = asyncio.create_task(news_ingest.scheduler_loop())
    yield
    news_task.cancel()
    try:
        await news_task
    except asyncio.CancelledError:
        pass
    await db.disconnect()
    await redis.disconnect()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Mock Exam Platform API",
    version="0.1.0",
    lifespan=lifespan,
    # Interactive docs publish the full API map. They expose no data (every data
    # endpoint requires a valid JWT), but there's no reason to hand attackers a
    # map in production.
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None if settings.is_production else "/redoc",
    openapi_url=None if settings.is_production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(me.router)
app.include_router(exams.router)
app.include_router(attempts.router)
app.include_router(reference.router)
app.include_router(mock_tests.router)
app.include_router(dashboard.router)
app.include_router(share.router)
app.include_router(news.router)
