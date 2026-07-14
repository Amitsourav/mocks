from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import attempts, exams, health, me
from app.core import db, redis
from app.core.config import get_settings

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
    yield
    await db.disconnect()
    await redis.disconnect()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Mock Exam Platform API",
    version="0.1.0",
    lifespan=lifespan,
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
